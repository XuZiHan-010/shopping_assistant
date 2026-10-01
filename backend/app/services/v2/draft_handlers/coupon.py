"""促销券草稿处理器（N3 阶段 C Task 4，PRD M6）。

券草稿与补货/调价不同：它创建一行**新**的 `Coupon`，而不是修改已有对象。草稿暂存时
（`services/v2/drafts.py`）已经预先分配好 `Coupon.id`（= `draft.target_id`），
`target_version` 固定为 0（"目标此刻不存在"），应用时按该 id 插入，
主键冲突（同一草稿被并发应用两次）由数据库唯一约束天然挡住。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import GuardrailRejectedError, InvalidRequestError, VersionConflictError
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.drafts import Draft
from app.models.promotion import Coupon
from app.schemas.v2.drafts import DraftKind
from app.services.v2.draft_handlers import HandlerRequest, HandlerResult
from app.services.v2.drafts import coupon_entry_id
from app.services.v2.guardrails import check_coupon, load_limits

#: 券草稿的目标版本恒为 0："此刻不存在"，与 `Draft.target_version >= 0` 的 CHECK 兼容。
UNCREATED_TARGET_VERSION: Final = 0


class CouponHandler:
    kind: DraftKind = DraftKind.COUPON

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
        entry_id = coupon_entry_id(draft)
        if request.accepted_entry_ids is not None and set(request.accepted_entry_ids) != {
            entry_id
        }:
            raise InvalidRequestError(
                details=[{"field": "accepted_entry_ids", "reason": "UNKNOWN_ENTRY"}]
            )
        if request.target_version != UNCREATED_TARGET_VERSION:
            raise VersionConflictError(scope="TARGET")

        payload = draft.payload
        is_full_reduction = payload["kind"] == "FULL_REDUCTION"
        limits = await load_limits(session, ctx.merchant_id)
        checks = check_coupon(
            discount_rate=(
                Decimal(str(payload["discount_rate"]))
                if payload["kind"] == "DISCOUNT"
                else None
            ),
            threshold_amount=(
                Decimal(str(payload["threshold_amount"]))
                if is_full_reduction and payload.get("threshold_amount") is not None
                else None
            ),
            discount_amount=(
                Decimal(str(payload["discount_amount"]))
                if is_full_reduction and payload.get("discount_amount") is not None
                else None
            ),
            limits=limits,
            locale=locale,
        )
        failed = [check for check in checks if not check.passed]
        if failed:
            raise GuardrailRejectedError(
                details=[check.model_dump(mode="json") for check in failed]
            )

        coupon = Coupon(
            id=draft.target_id,
            merchant_id=ctx.merchant_id,
            name=payload["name"],
            kind=payload["kind"],
            threshold_amount=(
                Decimal(str(payload["threshold_amount"]))
                if payload.get("threshold_amount") is not None
                else None
            ),
            discount_amount=(
                Decimal(str(payload["discount_amount"]))
                if payload.get("discount_amount") is not None
                else None
            ),
            discount_rate=(
                Decimal(str(payload["discount_rate"]))
                if payload.get("discount_rate") is not None
                else None
            ),
            scope=payload["scope"],
            product_ids=list(payload["product_ids"]),
            starts_at=datetime.fromisoformat(payload["starts_at"]),
            ends_at=datetime.fromisoformat(payload["ends_at"]),
            state="ACTIVE",
        )
        session.add(coupon)
        try:
            await session.flush()
        except IntegrityError as error:
            # 同一份已批准草稿被并发重放两次（例如客户端重试）：主键已存在，视为并发冲突。
            raise VersionConflictError(scope="TARGET") from error
        del now
        return HandlerResult(checks=checks, applied_entry_ids=[entry_id])
