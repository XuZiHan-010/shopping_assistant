"""商家售后决定：批准时复检版本与金额，并在同一事务写事实与事件。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    GuardrailRejectedError,
    IllegalStateTransitionError,
    InvalidRequestError,
    VersionConflictError,
)
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.after_sales import AfterSale, AfterSaleLine, AfterSaleReply
from app.models.analytics import OrderItem, Product, Refund, ReturnRecord, SupportTicket
from app.models.drafts import Draft
from app.models.events import InventoryEvent
from app.schemas.v2.after_sales import AfterSaleActor, AfterSaleState, AfterSaleType
from app.schemas.v2.drafts import DraftKind
from app.services.v2.after_sale_machine import IllegalTransition, transition
from app.services.v2.draft_handlers import HandlerRequest, HandlerResult
from app.services.v2.drafts import to_diff
from app.services.v2.orders import business_date_of
from app.services.v2.refund_calc import RefundLine, refundable


class Decision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_INFO = "REQUEST_INFO"
    RECEIVE = "RECEIVE"
    REFUND = "REFUND"


class DecisionPayload(BaseModel):
    """严格拒绝金额和未经定义的决定字段；不得相信模型写入的业务计算。"""

    model_config = ConfigDict(extra="forbid")

    decision: Decision
    rule_reference: str | None = Field(default=None, min_length=1, max_length=200)
    sellable: bool | None = None
    reply_text: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def conditional_fields(self) -> DecisionPayload:
        if self.decision is Decision.REJECT and not self.rule_reference:
            raise ValueError("拒绝售后必须附依据条款")
        if (self.decision is Decision.RECEIVE) != (self.sellable is not None):
            raise ValueError("确认收货必须明确标记是否可售，其他决定不得携带可售标记")
        return self


_TARGET: dict[Decision, AfterSaleState] = {
    Decision.APPROVE: AfterSaleState.APPROVED,
    Decision.REJECT: AfterSaleState.REJECTED,
    Decision.REQUEST_INFO: AfterSaleState.AWAITING_CUSTOMER_INFO,
    Decision.RECEIVE: AfterSaleState.RECEIVED,
    Decision.REFUND: AfterSaleState.REFUNDED,
}


class AfterSaleDecisionHandler:
    kind: DraftKind = DraftKind.AFTER_SALE_DECISION

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
        del locale
        applied_entries = [item.entry_id for item in to_diff(draft).entries]
        expected_entries = set(applied_entries)
        if (
            request.accepted_entry_ids is not None
            and set(request.accepted_entry_ids) != expected_entries
        ):
            raise InvalidRequestError(
                details=[{"field": "accepted_entry_ids", "reason": "UNKNOWN_ENTRY"}]
            )
        if draft.target_type != "AFTER_SALE":
            raise InvalidRequestError(details=[{"field": "target_type", "reason": "INVALID"}])
        payload = DecisionPayload.model_validate(draft.payload)
        sale = (
            await session.execute(
                select(AfterSale).where(
                    AfterSale.id == draft.target_id,
                    AfterSale.merchant_id == ctx.merchant_id,
                ).with_for_update().execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if sale is None or request.target_version != draft.target_version:
            raise VersionConflictError(scope="TARGET")
        if sale.state_version != draft.target_version:
            raise VersionConflictError(scope="TARGET")

        target = _TARGET[payload.decision]
        try:
            updated = await transition(
                session, merchant_id=ctx.merchant_id, after_sale_id=sale.id,
                target=target, actor=AfterSaleActor.MERCHANT, now=now,
            )
        except IllegalTransition:
            raise IllegalStateTransitionError from None
        if payload.decision is Decision.REFUND:
            await _record_refund(session, sale, now=now)
        elif payload.decision is Decision.RECEIVE:
            await _receive_return(session, sale, sellable=payload.sellable is True, now=now)
        ticket = await session.scalar(select(SupportTicket).where(
            SupportTicket.merchant_id == ctx.merchant_id,
            SupportTicket.after_sale_id == sale.id,
        ))
        if ticket is not None:
            ticket.ticket_status = "CLOSED" if updated.state == "CLOSED" else "PENDING"
        if payload.reply_text:
            session.add(AfterSaleReply(
                merchant_id=ctx.merchant_id, after_sale_id=sale.id,
                draft_id=draft.id, text=payload.reply_text, sent_at=now,
            ))
            await session.flush()
        return HandlerResult(checks=[], applied_entry_ids=applied_entries)


async def _record_refund(session: AsyncSession, sale: AfterSale, *, now: datetime) -> None:
    lines = list((await session.scalars(select(AfterSaleLine).where(
        AfterSaleLine.after_sale_id == sale.id
    ))).all())
    if not lines:
        raise GuardrailRejectedError(details=[{"reason": "NO_REFUND_LINES"}])
    total = Decimal("0.00")
    for line in lines:
        item = await session.scalar(select(OrderItem).where(
            OrderItem.id == line.order_item_id,
            OrderItem.merchant_id == sale.merchant_id,
            OrderItem.order_id == sale.order_id,
        ).with_for_update())
        if item is None:
            raise VersionConflictError(scope="TARGET")
        paid = await session.scalar(select(func.coalesce(func.sum(Refund.refund_amount), 0)).where(
            Refund.merchant_id == sale.merchant_id,
            Refund.order_item_id == item.id,
            Refund.refund_status == "REFUNDED",
        ))
        available = refundable(RefundLine(item.line_total, Decimal(str(paid))))
        amount = min(line.refund_amount, available)
        line.refund_amount = amount
        if amount > 0:
            session.add(Refund(
                merchant_id=sale.merchant_id, business_date=business_date_of(now),
                order_item_id=item.id, after_sale_id=sale.id,
                refund_amount=amount, refund_reason="AFTER_SALE",
                refund_status="REFUNDED", refunded_at=now,
            ))
        total += amount
    if total <= 0:
        raise GuardrailRejectedError(details=[{"reason": "ALREADY_REFUNDED"}])
    sale.refund_amount = total
    await session.flush()


async def _receive_return(
    session: AsyncSession, sale: AfterSale, *, sellable: bool, now: datetime
) -> None:
    if sale.after_sale_type != AfterSaleType.RETURN_REFUND.value:
        raise IllegalStateTransitionError
    lines = list((await session.scalars(select(AfterSaleLine).where(
        AfterSaleLine.after_sale_id == sale.id
    ))).all())
    for line in lines:
        item = await session.scalar(select(OrderItem).where(
            OrderItem.id == line.order_item_id,
            OrderItem.merchant_id == sale.merchant_id,
            OrderItem.order_id == sale.order_id,
        ))
        if item is None:
            raise VersionConflictError(scope="TARGET")
        session.add(ReturnRecord(
            merchant_id=sale.merchant_id, business_date=business_date_of(now),
            order_item_id=item.id, after_sale_id=sale.id,
            return_quantity=line.quantity, return_reason="AFTER_SALE",
            return_status="RECEIVED", logistics_status="DELIVERED", returned_at=now,
        ))
        if sellable:
            product = await session.scalar(select(Product).where(
                Product.id == item.product_id, Product.merchant_id == sale.merchant_id
            ).with_for_update())
            if product is None:
                raise VersionConflictError(scope="TARGET")
            product.stock_on_hand += line.quantity
            session.add(InventoryEvent(
                merchant_id=sale.merchant_id, subject_id=product.id,
                event_type="RETURN_RESTOCK", occurred_at=now,
                dedupe_key=f"RETURN_RESTOCK:{sale.id}:{line.id}",
                payload={"delta": line.quantity, "after_sale_id": str(sale.id)},
            ))
    await session.flush()
