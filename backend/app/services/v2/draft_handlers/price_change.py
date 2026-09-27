"""调价草稿处理器（N3 阶段 C Task 4，PRD M6）。

第 5–7 步：目标基数复检 → 按当时生效的护栏复检 → 条件更新商品价格。
护栏**必须**按应用时刻生效的配置复检（D9②），不沿用起草时的快照——因此这里重新调用
`check_price_change()`，而不是照抄 `draft.guardrail_snapshot` 里的结果。

不新建独立的定价事件表：`change_ledger`（骨架统一写入）已经记录了谁起草、谁批准、
护栏复检结果与应用时间，这对调价这类"改一个标量字段"的操作已经是完整的审计轨迹；
`InventoryEvent`/`AfterSaleEvent` 这类独立事件表是为了给同一个 `subject_id` 累积
一条可重放的历史（库存增减序列、售后状态迁移），调价没有这种"多次增量叠加"的需求，
新增一张表和迁移不会带来额外可观测性，只会增加数据源。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import GuardrailRejectedError, InvalidRequestError, VersionConflictError
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.analytics import Product
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftKind, GuardrailCheckResult
from app.services.v2.draft_handlers import HandlerRequest, HandlerResult
from app.services.v2.drafts import price_change_entry_id
from app.services.v2.guardrails import check_price_change, load_limits

#: `target_version` 编码为价格的分值（与草稿的 `base_price` 一一对应），沿用
#: `RestockHandler` 的模式："目标版本"就是并发比对用的那个基数本身，不是自增计数器。


class PriceChangeHandler:
    kind: DraftKind = DraftKind.PRICE_CHANGE

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
        entry_id = price_change_entry_id(draft)
        if request.accepted_entry_ids is not None and set(request.accepted_entry_ids) != {
            entry_id
        }:
            raise InvalidRequestError(
                details=[{"field": "accepted_entry_ids", "reason": "UNKNOWN_ENTRY"}]
            )

        base_price = Decimal(str(draft.payload["base_price"]))
        new_price = Decimal(str(draft.payload["new_price"]))
        if request.target_version != draft.target_version:
            # 请求自报的目标版本必须就是草案的价格基数（分），否则是拿旧界面在批准。
            raise VersionConflictError(scope="TARGET")

        checks = await _recheck_guardrails(session, ctx, base_price, new_price, locale)

        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(Product)
                .where(
                    Product.id == draft.target_id,
                    Product.merchant_id == ctx.merchant_id,
                    Product.price == base_price,
                )
                .values(price=new_price)
            ),
        )
        if result.rowcount != 1:
            raise VersionConflictError(scope="TARGET")
        del now
        return HandlerResult(checks=checks, applied_entry_ids=[entry_id])


async def _recheck_guardrails(
    session: AsyncSession,
    ctx: SessionContext,
    base_price: Decimal,
    new_price: Decimal,
    locale: SupportedLocale,
) -> list[GuardrailCheckResult]:
    limits = await load_limits(session, ctx.merchant_id)
    checks = check_price_change(
        current_price=base_price, new_price=new_price, limits=limits, locale=locale
    )
    failed = [check for check in checks if not check.passed]
    if failed:
        raise GuardrailRejectedError(details=[check.model_dump(mode="json") for check in failed])
    return checks
