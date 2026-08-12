"""签名 CSV 下载端点。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import get_export_service
from app.core.errors import error_responses
from app.services.export_service import ExportService

router = APIRouter(tags=["exports"])


@router.get(
    "/exports/{export_id}",
    responses=error_responses(403, 404, 410, 422),
)
async def download_export(
    export_id: UUID,
    merchant_id: UUID,
    expires_at: Annotated[int, Query(ge=0)],
    signature: Annotated[str, Query(min_length=32, max_length=128)],
    service: Annotated[ExportService, Depends(get_export_service)],
) -> Response:
    content = await service.download(
        export_id=export_id,
        merchant_id=merchant_id,
        expires_at=expires_at,
        signature=signature,
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
        },
    )
