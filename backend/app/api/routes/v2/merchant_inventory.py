"""库存告警（PRD M5，契约 §8.12.3）：`GET /api/v2/merchant/inventory/alerts`。

本组**没有任何库存写端点**（§8.12.2 不变量 4）：补货、下架、降价都经草稿审批。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import require_merchant_session
from app.api.v2_deps import get_cursor_codec, merchant_cursor_scope
from app.core.errors import error_responses
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.repositories.v2.inventory import InventoryReadRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.merchant_ops import InventoryAlert, InventoryAlertKind
from app.services.v2.cursor import CursorCodec
from app.services.v2.inventory_alerts import AlertRules, alerts_for, sort_key

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-inventory"])


@router.get(
    "/inventory/alerts",
    response_model=CursorPage[InventoryAlert],
    responses=error_responses(401, 403, 422, 503),
)
async def list_inventory_alerts(
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    kind: InventoryAlertKind | None = None,
) -> CursorPage[InventoryAlert]:
    now = datetime.now(UTC)
    facts = await InventoryReadRepository(session).facts_for_merchant(ctx.merchant_id, now=now)
    alerts = alerts_for(facts, rules=AlertRules(), now=now, kind=kind)
    scope = merchant_cursor_scope(
        ctx,
        endpoint="merchant.inventory.alerts",
        resource="INVENTORY_ALERT",
        filters={"kind": kind.value if kind else None},
        locale=locale,
        limit=limit,
        secret=principal_secret,
    )
    return codec.page(
        alerts,
        key=lambda alert: tuple(str(part) for part in sort_key(alert)),
        scope=scope,
        cursor=cursor,
        now=now,
    )
