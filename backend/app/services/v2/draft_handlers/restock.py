"""补货草稿处理器：从 `draft_apply.py` 原样移出的 N2 补货逻辑（N3 阶段 A Task 5）。

第 5–7 步：显式勾选复核 → 目标基数复检 → 按当时生效的护栏复检 → 条件更新库存 → 追加库存事件。
草稿置 `APPLIED` 与写账本由骨架统一做；本处理器不提交事务、不碰证据。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import GuardrailRejectedError, InvalidRequestError, VersionConflictError
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.analytics import Product
from app.models.drafts import Draft
from app.models.events import InventoryEvent
from app.schemas.v2.drafts import DraftKind, GuardrailCheckResult
from app.services.v2.draft_handlers import HandlerRequest, HandlerResult
from app.services.v2.drafts import restock_entry_id
from app.services.v2.guardrails import check_restock, load_limits

#: 库存事件类型；账本与事件是两条互补的记录：事件说库存怎么变，账本说谁批准的。
RESTOCK_EVENT: Final = "MERCHANT_RESTOCK"


class RestockHandler:
    kind: DraftKind = DraftKind.RESTOCK

    async def apply(
        self,
        session: AsyncSession,
        ctx: SessionContext,
        draft: Draft,
        request: HandlerRequest,
        *,
        now: datetime,
        locale: SupportedLocale,
    ) -> HandlerResult:
        entry_id = restock_entry_id(draft)
        # N2 补货草稿只有一个变更条目；显式勾选必须确实覆盖该条目。
        # 拒绝任意其他 ID，避免界面未批准实际变更却照样应用库存写入。
        if request.accepted_entry_ids is not None and set(request.accepted_entry_ids) != {entry_id}:
            raise InvalidRequestError(
                details=[{"field": "accepted_entry_ids", "reason": "UNKNOWN_ENTRY"}]
            )
        base = int(draft.payload["base_on_hand"])
        delta = int(draft.payload["delta"])
        if request.target_version != base:
            # 请求自报的目标版本必须就是草案的变更基数，否则是拿旧界面在批准。
            raise VersionConflictError(scope="TARGET")

        checks = await _recheck_guardrails(session, ctx, delta, locale)
        # 条件更新是最后一道并发防线：基数被别的事务改过时影响行数为 0。
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(Product)
                .where(
                    Product.id == draft.target_id,
                    Product.merchant_id == ctx.merchant_id,
                    Product.stock_on_hand == base,
                )
                .values(stock_on_hand=Product.stock_on_hand + delta)
            ),
        )
        if result.rowcount != 1:
            raise VersionConflictError(scope="TARGET")

        session.add(
            InventoryEvent(
                merchant_id=ctx.merchant_id,
                subject_id=draft.target_id,
                event_type=RESTOCK_EVENT,
                occurred_at=now,
                dedupe_key=f"{RESTOCK_EVENT}:{draft.id}",
                payload={"delta": delta, "base_on_hand": base, "draft_id": str(draft.id)},
            )
        )
        return HandlerResult(checks=checks, applied_entry_ids=[entry_id])


async def _recheck_guardrails(
    session: AsyncSession, ctx: SessionContext, delta: int, locale: SupportedLocale
) -> list[GuardrailCheckResult]:
    """按**当时生效**的配置重查，不沿用预检快照（D9②）。"""

    limits = await load_limits(session, ctx.merchant_id)
    checks = check_restock(delta, limits=limits, locale=locale)
    failed = [check for check in checks if not check.passed]
    if failed:
        raise GuardrailRejectedError(details=[check.model_dump(mode="json") for check in failed])
    return checks
