"""上下架草稿处理器（PRD M5）。

第 5–7 步：显式勾选复核 → 起草时状态复检 → 按当前数据重跑护栏 → 条件更新商品状态。
与调价一样不新建事件表：`change_ledger` 已记录谁起草、谁批准与护栏复检结果；
上下架不改在库量，也不写库存事件。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import GuardrailRejectedError, InvalidRequestError, VersionConflictError
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.analytics import Product
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftKind
from app.services.v2.draft_handlers import HandlerRequest, HandlerResult
from app.services.v2.drafts import LISTING_STATUS_VERSION, listing_status_entry_id
from app.services.v2.guardrails import check_listing_status


class ListingStatusHandler:
    kind: DraftKind = DraftKind.LISTING_STATUS

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
        entry_id = listing_status_entry_id(draft)
        if request.accepted_entry_ids is not None and set(request.accepted_entry_ids) != {
            entry_id
        }:
            raise InvalidRequestError(
                details=[{"field": "accepted_entry_ids", "reason": "UNKNOWN_ENTRY"}]
            )

        action = str(draft.payload["action"])
        base_status = str(draft.payload["base_status"])
        new_status = str(draft.payload["new_status"])
        # 请求自报的目标版本必须就是起草时状态编码，否则是拿旧界面在批准。
        if request.target_version != draft.target_version:
            raise VersionConflictError(scope="TARGET")
        if LISTING_STATUS_VERSION.get(base_status) != draft.target_version:
            raise VersionConflictError(scope="TARGET")

        # 护栏按**应用时**的真实状态重跑（D9②），不沿用起草快照。
        current_status = await session.scalar(
            select(Product.status).where(
                Product.id == draft.target_id, Product.merchant_id == ctx.merchant_id
            )
        )
        if current_status is None or current_status != base_status:
            # 起草后状态被别处改过：与调价/补货一致，报目标版本冲突而不是护栏拒绝。
            raise VersionConflictError(scope="TARGET")
        checks = check_listing_status(action=action, current_status=current_status, locale=locale)
        failed = [check for check in checks if not check.passed]
        if failed:
            raise GuardrailRejectedError(
                details=[check.model_dump(mode="json") for check in failed]
            )

        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(Product)
                .where(
                    Product.id == draft.target_id,
                    Product.merchant_id == ctx.merchant_id,
                    Product.status == base_status,
                )
                .values(status=new_status)
            ),
        )
        if result.rowcount != 1:
            raise VersionConflictError(scope="TARGET")
        del now
        return HandlerResult(checks=checks, applied_entry_ids=[entry_id])
