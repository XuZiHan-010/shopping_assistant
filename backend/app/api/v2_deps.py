"""v2 商家端点共用的依赖：签名游标、主体摘要与操作证据密钥。

放在会话依赖之外单独一层，是因为这些构件与"谁在调用"无关，只与"服务端用哪把密钥"
有关；路由按需组合，避免每个路由各自从 `Settings` 里挑密钥。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends

from app.api.dependencies import get_app_settings, get_principal_secret
from app.core.config import Settings
from app.core.session import SessionContext, principal_digest
from app.localization.locales import SupportedLocale
from app.services.v2.approval_evidence import ApprovalEvidenceService
from app.services.v2.cursor import CursorCodec, CursorScope

#: 与 `dependencies.py` 同一条约定：生产必配真实密钥，本地与测试用固定开发值。
_DEV_SIGNING_SECRET = "development-export-signing-secret"


def get_signing_secret(settings: Annotated[Settings, Depends(get_app_settings)]) -> str:
    """游标与操作证据的共同根密钥；各用途再各自派生子密钥，不直接使用裸密钥。"""

    return settings.export_signing_secret or _DEV_SIGNING_SECRET


def get_cursor_codec(secret: Annotated[str, Depends(get_signing_secret)]) -> CursorCodec:
    return CursorCodec(secret=secret)


def get_approval_evidence_service(
    secret: Annotated[str, Depends(get_signing_secret)],
) -> ApprovalEvidenceService:
    """审批证据服务；子密钥按用途派生，与游标、导出链接互不通用。"""

    return ApprovalEvidenceService(secret=secret)


def merchant_cursor_scope(
    ctx: SessionContext,
    *,
    endpoint: str,
    resource: str,
    filters: dict[str, Any],
    locale: SupportedLocale,
    limit: int,
    secret: bytes,
) -> CursorScope:
    """商家列表端点的游标绑定：主体只进摘要，明文标识不入游标载荷。"""

    return CursorScope(
        endpoint=endpoint,
        role=ctx.role.value,
        principal_digest=principal_digest(ctx, secret=secret),
        merchant_id=str(ctx.merchant_id),
        resource=resource,
        filters=filters,
        locale=locale.value,
        limit=limit,
    )


__all__ = [
    "get_approval_evidence_service",
    "get_cursor_codec",
    "get_principal_secret",
    "get_signing_secret",
    "merchant_cursor_scope",
]
