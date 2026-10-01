"""签名 CSV 下载端点。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import get_database, get_export_service
from app.core.errors import error_responses
from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.repositories.audit import AuditRepository
from app.services.export_service import ExportService

router = APIRouter(tags=["exports"])

#: 与创建审计 `EXPORT_CREATED`（`app/tools/merchant/export.py`）配对，
#: PRD M7/SEC10 要求两者分别审计。
EXPORT_DOWNLOADED_EVENT = "EXPORT_DOWNLOADED"


@router.get(
    "/exports/{export_id}",
    responses=error_responses(403, 404, 410, 422),
)
async def download_export(
    request: Request,
    export_id: UUID,
    merchant_id: UUID,
    expires_at: Annotated[int, Query(ge=0)],
    signature: Annotated[str, Query(min_length=32, max_length=128)],
    service: Annotated[ExportService, Depends(get_export_service)],
    database: Annotated[Database, Depends(get_database)],
    # 这条端点是浏览器直接打开的签名 URL，没有 `Accept-Language`；导出语言
    # 只能来自这个由 `ExportService.create()` 签发时写入的查询参数,并且必须
    # 经签名验证——见 `ExportService.download()`/`_signature()`。旧签名不带
    # 这个参数时保持 `None`，`ExportService` 按 zh-CN 解释（Task 8 Step 7）。
    locale: Annotated[SupportedLocale | None, Query()] = None,
) -> Response:
    content = await service.download(
        export_id=export_id,
        merchant_id=merchant_id,
        expires_at=expires_at,
        signature=signature,
        locale=locale or SupportedLocale.ZH_CN,
    )
    # 走到这里签名已验证通过，`merchant_id` 可信；失败的下载不记为「已下载」。
    await AuditRepository(database).record_event(
        merchant_id=merchant_id,
        event_type=EXPORT_DOWNLOADED_EVENT,
        resource_type="EXPORT",
        resource_id=str(export_id),
        request_id=str(request.state.request_id),
    )
    return Response(
        # ExportService.download() 已经在字符串开头拼好了 BOM(`﻿`)；这里
        # 只能用 utf-8 编码原样落地，utf-8-sig 会再自动加一次 BOM 字节，导致
        # 下载出来的 CSV 开头是两段 BOM。
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="borough-detail-export.csv"',
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "Content-Language": str(locale or SupportedLocale.ZH_CN),
        },
    )
