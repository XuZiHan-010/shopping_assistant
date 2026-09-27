"""顾客售后申请的确定性预检与界面确认提交。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConfirmationRequiredError,
    GuardrailRejectedError,
    IllegalStateTransitionError,
    InvalidRequestError,
)
from app.core.session import SessionContext, buyer_alias, principal_digest
from app.llm.client import LlmClient
from app.localization.locales import SupportedLocale
from app.models.after_sales import (
    AfterSale,
    AfterSaleChallengePreview,
    AfterSaleLine,
    AfterSaleReply,
    AfterSaleSupplement,
)
from app.models.analytics import Order, OrderItem, Refund, SupportTicket
from app.models.conversation import Conversation, Message
from app.models.events import AfterSaleEvent, FulfillmentEvent
from app.repositories.audit import AuditRepository
from app.repositories.v2.idempotency import IdempotencyRepository
from app.repositories.v2.operation_evidence import OperationEvidenceRepository
from app.schemas.v2.after_sales import (
    AfterSaleActor,
    AfterSaleChallengeLine,
    AfterSaleChallengeSummary,
    AfterSaleConfirmationChallenge,
    AfterSaleCreateRequest,
    AfterSaleIneligibleDetail,
    AfterSaleState,
    AfterSaleSummary,
    AfterSaleSupplementRequest,
    AfterSaleType,
    ConversationSnapshot,
    CustomerAfterSaleDetailResponse,
    MerchantAfterSaleDetailResponse,
    MerchantAfterSaleSummary,
)
from app.schemas.v2.after_sales import (
    AfterSaleEvent as AfterSaleEventOut,
)
from app.schemas.v2.after_sales import (
    AfterSaleLine as AfterSaleLineOut,
)
from app.schemas.v2.after_sales import AfterSaleReply as AfterSaleReplyOut
from app.schemas.v2.after_sales import (
    AfterSaleSupplement as AfterSaleSupplementOut,
)
from app.schemas.v2.common import yuan_to_cents
from app.schemas.v2.trade import OrderItemPriceSnapshot
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.v2.after_sale_eligibility import OrderFacts, check_eligibility
from app.services.v2.after_sale_machine import IllegalTransition, transition
from app.services.v2.approval_evidence import (
    ApprovalEvidenceService,
    CustomerConfirmationBinding,
)
from app.services.v2.conversation_summary import (
    SummaryResult,
    redact_sensitive_text,
    summarize_messages,
)
from app.services.v2.customer_signals import derive_after_sale_signals
from app.services.v2.idempotency import run_idempotent
from app.services.v2.orders import require_owned_order
from app.services.v2.refund_calc import RefundLine, refundable

CREATE_OPERATION: Final = "shop.after_sales.create"


@dataclass(frozen=True)
class _Precheck:
    order: Order
    lines: list[tuple[OrderItem, Decimal]]
    summary: AfterSaleChallengeSummary


def _digest(payload: AfterSaleCreateRequest) -> str:
    business = payload.model_dump(exclude={"confirmation_token", "client_request_id"}, mode="json")
    encoded = json.dumps(business, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _binding(
    ctx: SessionContext, payload: AfterSaleCreateRequest, *, secret: bytes
) -> CustomerConfirmationBinding:
    return CustomerConfirmationBinding(
        session_record_id=str(ctx.session_record_id),
        merchant_id=str(ctx.merchant_id),
        buyer_digest=principal_digest(ctx, secret=secret),
        order_id=payload.order_id,
        after_sale_type=payload.after_sale_type.value,
        request_digest=_digest(payload),
    )


async def _precheck(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    payload: AfterSaleCreateRequest,
    audits: AuditRepository,
    request_id: str,
    now: datetime,
    lock_order: bool = False,
) -> _Precheck:
    order = await require_owned_order(
        session, ctx=ctx, order_id=payload.order_id, audits=audits, request_id=request_id
    )
    if lock_order:
        # 两个不同幂等键可同时拿到预览；提交阶段按订单串行复检，不能各自创建售后。
        order = (
            await session.execute(
                select(Order)
                .where(Order.id == order.id, Order.merchant_id == ctx.merchant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
    delivered_at = await session.scalar(
        select(func.max(FulfillmentEvent.occurred_at)).where(
            FulfillmentEvent.merchant_id == ctx.merchant_id,
            FulfillmentEvent.subject_id == order.id,
            FulfillmentEvent.event_type == "DELIVERED",
        )
    )
    in_progress = bool(
        await session.scalar(
            select(AfterSale.id)
            .where(
                AfterSale.merchant_id == ctx.merchant_id,
                AfterSale.buyer_key == ctx.buyer_key,
                AfterSale.order_id == order.id,
                AfterSale.state != "CLOSED",
            )
            .limit(1)
        )
    )
    items = list(
        (
            await session.scalars(
                select(OrderItem)
                .where(OrderItem.order_id == order.id, OrderItem.merchant_id == ctx.merchant_id)
                .order_by(OrderItem.id)
            )
        ).all()
    )
    selected = set(payload.order_item_ids)
    if selected and (
        len(selected) != len(payload.order_item_ids) or selected - {str(item.id) for item in items}
    ):
        raise InvalidRequestError(details=[{"field": "order_item_ids", "reason": "UNKNOWN"}])
    chosen = items if not selected else [item for item in items if str(item.id) in selected]
    paid_refunds: dict[UUID, Decimal] = {}
    if items:
        rows = (
            await session.execute(
                select(Refund.order_item_id, func.sum(Refund.refund_amount))
                .where(
                    Refund.merchant_id == ctx.merchant_id,
                    Refund.order_item_id.in_([item.id for item in items]),
                    Refund.refund_status == "REFUNDED",
                )
                .group_by(Refund.order_item_id)
            )
        ).all()
        paid_refunds = {item_id: amount for item_id, amount in rows}
    facts = OrderFacts(
        lifecycle_origin=order.lifecycle_origin,
        payment_status=order.payment_status,
        fulfillment_status=order.fulfillment_status,
        delivered_at=delivered_at,
        already_in_progress=in_progress,
        already_refunded=sum(paid_refunds.values(), Decimal("0")) >= order.paid_amount,
    )
    eligibility = check_eligibility(facts, now=now)
    if payload.after_sale_type not in eligibility.allowed_types:
        reason = eligibility.reason_code or "ORDER_NOT_DELIVERED"
        detail = AfterSaleIneligibleDetail(reason=reason, rule_reference=eligibility.rule_ref)
        raise GuardrailRejectedError(details=[detail.model_dump(mode="json")])
    amounts = [
        (item, refundable(RefundLine(item.line_total, paid_refunds.get(item.id, Decimal("0")))))
        for item in chosen
    ]
    if payload.after_sale_type != AfterSaleType.TICKET and not any(
        amount > 0 for _, amount in amounts
    ):
        detail = AfterSaleIneligibleDetail(
            reason="ALREADY_REFUNDED", rule_reference="平台演示售后规则：已退金额不可再次申请"
        )
        raise GuardrailRejectedError(details=[detail.model_dump(mode="json")])
    summary = AfterSaleChallengeSummary(
        order_id=str(order.id),
        after_sale_type=payload.after_sale_type,
        lines=[
            AfterSaleChallengeLine(
                order_item_id=str(item.id),
                name=item.title_snapshot or "商品",
                quantity=item.quantity,
                line_total_cents=yuan_to_cents(item.line_total),
            )
            for item, _ in amounts
        ],
        estimated_refund_cents=(
            None
            if payload.after_sale_type == AfterSaleType.TICKET
            else sum(yuan_to_cents(amount) for _, amount in amounts)
        ),
        reason=redact_sensitive_text(payload.reason),
        conversation_summary_status=(
            "UNAVAILABLE" if payload.include_conversation_summary else "NOT_SHARED"
        ),
        conversation_summary=None,
    )
    return _Precheck(order=order, lines=amounts, summary=summary)


async def issue_challenge(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    payload: AfterSaleCreateRequest,
    audits: AuditRepository,
    request_id: str,
    now: datetime,
    evidence: ApprovalEvidenceService,
    secret: bytes,
    summary_llm: LlmClient,
) -> AfterSaleConfirmationChallenge:
    precheck = await _precheck(
        session, ctx=ctx, payload=payload, audits=audits, request_id=request_id, now=now
    )
    issued = evidence.issue(_binding(ctx, payload, secret=secret), now=now)
    challenge_summary = precheck.summary
    if payload.include_conversation_summary:
        result = await _summarize_for_order(
            session, ctx=ctx, precheck=precheck, secret=secret, llm=summary_llm
        )
        challenge_summary = challenge_summary.model_copy(
            update={
                "conversation_summary_status": (
                    "INCLUDED" if result.status == "AVAILABLE" else "UNAVAILABLE"
                ),
                "conversation_summary": result.text,
            }
        )
        session.add(
            AfterSaleChallengePreview(
                nonce=issued.nonce,
                merchant_id=ctx.merchant_id,
                buyer_digest=principal_digest(ctx, secret=secret),
                status=result.status,
                text=result.text,
                unavailable_reason=result.reason,
            )
        )
    await OperationEvidenceRepository(session).register(
        purpose=evidence.purpose,
        nonce=issued.nonce,
        issued_at=now,
        expires_at=issued.expires_at,
    )
    return AfterSaleConfirmationChallenge(
        confirmation_token=issued.token, expires_at=issued.expires_at, summary=challenge_summary
    )


async def _summarize_for_order(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    precheck: _Precheck,
    secret: bytes,
    llm: LlmClient,
) -> SummaryResult:
    owner_id = principal_digest(ctx, secret=secret)
    rows = list(
        (
            await session.scalars(
                select(Message.content)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(
                    Conversation.merchant_id == ctx.merchant_id,
                    Conversation.owner_kind == "BOUND_PRINCIPAL",
                    Conversation.owner_id == owner_id,
                    Conversation.surface == "SHOP",
                    Conversation.deleted_at.is_(None),
                    Message.merchant_id == ctx.merchant_id,
                    Message.role == "USER",
                )
                .order_by(Message.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    identifiers = [str(precheck.order.id)] + [str(item.product_id) for item, _ in precheck.lines]
    return await summarize_messages(
        rows,
        identifiers=identifiers,
        buyer_key=ctx.buyer_key or "",
        llm=llm,
    )


async def confirm_after_sale(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    payload: AfterSaleCreateRequest,
    audits: AuditRepository,
    request_id: str,
    now: datetime,
    evidence: ApprovalEvidenceService,
    secret: bytes,
) -> dict[str, Any]:
    async def create() -> dict[str, Any]:
        # 归属先于证据错误，避免对跨主体订单透露令牌状态。
        await require_owned_order(
            session, ctx=ctx, order_id=payload.order_id, audits=audits, request_id=request_id
        )
        verified = evidence.verify(
            payload.confirmation_token, _binding(ctx, payload, secret=secret), now=now
        )
        if not await OperationEvidenceRepository(session).consume(
            purpose=evidence.purpose, nonce=verified.nonce, now=now
        ):
            evidence.reject_consumed()
        precheck = await _precheck(
            session,
            ctx=ctx,
            payload=payload,
            audits=audits,
            request_id=request_id,
            now=now,
            lock_order=True,
        )
        preview: AfterSaleChallengePreview | None = None
        if payload.include_conversation_summary:
            preview = await session.scalar(
                select(AfterSaleChallengePreview).where(
                    AfterSaleChallengePreview.nonce == verified.nonce,
                    AfterSaleChallengePreview.merchant_id == ctx.merchant_id,
                    AfterSaleChallengePreview.buyer_digest == principal_digest(ctx, secret=secret),
                )
            )
            if preview is None:
                raise ConfirmationRequiredError
        assert ctx.buyer_key is not None
        kind = payload.after_sale_type
        amount = (
            None
            if kind == AfterSaleType.TICKET
            else sum((value for _, value in precheck.lines), Decimal("0.00"))
        )
        record = AfterSale(
            merchant_id=ctx.merchant_id,
            buyer_key=ctx.buyer_key,
            order_id=precheck.order.id,
            after_sale_type=kind.value,
            state="PENDING_MERCHANT",
            reason=precheck.summary.reason,
            refund_amount=amount,
            state_version=1,
            conversation_summary_status=(preview.status if preview is not None else "NOT_SHARED"),
            conversation_summary_text=preview.text if preview is not None else None,
            conversation_summary_reason=(
                preview.unavailable_reason if preview is not None else None
            ),
        )
        session.add(record)
        await session.flush()
        for item, value in precheck.lines:
            session.add(
                AfterSaleLine(
                    after_sale_id=record.id,
                    order_item_id=item.id,
                    quantity=item.quantity,
                    refund_amount=Decimal("0") if kind == AfterSaleType.TICKET else value,
                )
            )
        session.add(
            SupportTicket(
                merchant_id=ctx.merchant_id,
                business_date=now.date(),
                ticket_no=f"as-{record.id.hex[:16]}",
                order_id=precheck.order.id,
                after_sale_id=record.id,
                ticket_status="OPEN",
                ticket_reason="AFTER_SALE",
                opened_at=now,
            )
        )
        session.add(
            AfterSaleEvent(
                merchant_id=ctx.merchant_id,
                subject_id=record.id,
                event_type="PENDING_MERCHANT",
                occurred_at=now,
                dedupe_key=f"after-sale:{record.id}:1",
                payload={"from_state": None, "to_state": "PENDING_MERCHANT", "actor": "CUSTOMER"},
            )
        )
        await derive_after_sale_signals(
            session,
            merchant_id=ctx.merchant_id,
            kind=kind,
            sale_id=record.id,
            products=[
                (item.product_id, item.title_snapshot or "商品") for item, _ in precheck.lines
            ],
            now=now,
        )
        precheck.order.after_sale_status = "ACTIVE"
        await session.flush()
        await session.refresh(record)
        return AfterSaleSummary(
            id=str(record.id),
            order_id=str(record.order_id),
            after_sale_type=kind,
            state="PENDING_MERCHANT",
            refund_amount_cents=None if amount is None else yuan_to_cents(amount),
            created_at=record.created_at,
            updated_at=record.updated_at,
        ).model_dump(mode="json")

    return await run_idempotent(
        repo=IdempotencyRepository(session),
        ctx=ctx,
        secret=secret,
        operation=CREATE_OPERATION,
        client_request_id=payload.client_request_id,
        request_digest=_digest(payload),
        response_status=201,
        execute=create,
    )


def to_summary(record: AfterSale) -> AfterSaleSummary:
    return AfterSaleSummary(
        id=str(record.id),
        order_id=str(record.order_id),
        after_sale_type=record.after_sale_type,
        state=record.state,
        refund_amount_cents=(
            None if record.refund_amount is None else yuan_to_cents(record.refund_amount)
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def list_sales(
    session: AsyncSession,
    ctx: SessionContext,
    *,
    customer: bool,
    state: str | None = None,
) -> list[AfterSale]:
    query = select(AfterSale).where(AfterSale.merchant_id == ctx.merchant_id)
    if customer:
        assert ctx.buyer_key is not None
        query = query.where(AfterSale.buyer_key == ctx.buyer_key)
    if state is not None:
        query = query.where(AfterSale.state == state)
    return list(
        (
            await session.scalars(query.order_by(AfterSale.created_at.desc(), AfterSale.id.desc()))
        ).all()
    )


async def require_owned_sale(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    sale_id: str,
    audits: AuditRepository,
    request_id: str,
    customer: bool,
) -> AfterSale:
    async def fetch() -> ScopeLookupResult[AfterSale]:
        try:
            target = UUID(sale_id)
        except ValueError:
            target = None
        query = select(AfterSale).where(
            AfterSale.id == target, AfterSale.merchant_id == ctx.merchant_id
        )
        if customer:
            query = query.where(AfterSale.buyer_key == ctx.buyer_key)
        record = (await session.execute(query)).scalar_one_or_none()
        return ScopeLookupResult(resource=record, target_exists=None)

    return await require_owned(
        fetch,
        ctx=ctx,
        audits=audits,
        resource_type="after_sale",
        resource_id=sale_id,
        request_id=request_id,
    )


def merchant_summary(
    record: AfterSale, *, alias_secret: bytes, locale: SupportedLocale
) -> MerchantAfterSaleSummary:
    return MerchantAfterSaleSummary(
        **to_summary(record).model_dump(),
        buyer_alias=buyer_alias(alias_secret, record.merchant_id, record.buyer_key, locale),
        first_response_due_at=record.created_at + timedelta(hours=24),
    )


async def sale_detail(
    session: AsyncSession,
    record: AfterSale,
    *,
    customer: bool,
    alias_secret: bytes | None = None,
    locale: SupportedLocale = SupportedLocale.ZH_CN,
) -> CustomerAfterSaleDetailResponse | MerchantAfterSaleDetailResponse:
    lines = list(
        (
            await session.scalars(
                select(AfterSaleLine)
                .where(AfterSaleLine.after_sale_id == record.id)
                .order_by(AfterSaleLine.id)
            )
        ).all()
    )
    order_items = (
        {
            item.id: item
            for item in (
                await session.scalars(
                    select(OrderItem).where(
                        OrderItem.id.in_([line.order_item_id for line in lines]),
                        OrderItem.merchant_id == record.merchant_id,
                    )
                )
            ).all()
        }
        if lines
        else {}
    )
    line_models = []
    for line in lines:
        item = order_items[line.order_item_id]
        line_models.append(
            AfterSaleLineOut(
                snapshot=OrderItemPriceSnapshot(
                    order_item_id=str(item.id),
                    product_id=str(item.product_id),
                    name=item.title_snapshot or "商品",
                    quantity=item.quantity,
                    unit_price_cents=yuan_to_cents(item.unit_price),
                    discount_cents=yuan_to_cents(item.discount_amount),
                    line_total_cents=yuan_to_cents(item.line_total),
                ),
                refund_cents=yuan_to_cents(line.refund_amount),
            )
        )
    events = list(
        (
            await session.scalars(
                select(AfterSaleEvent)
                .where(
                    AfterSaleEvent.merchant_id == record.merchant_id,
                    AfterSaleEvent.subject_id == record.id,
                )
                .order_by(AfterSaleEvent.occurred_at, AfterSaleEvent.id)
            )
        ).all()
    )
    event_models = [
        AfterSaleEventOut(
            id=str(event.id),
            from_state=event.payload.get("from_state"),
            to_state=event.event_type,
            actor=event.payload["actor"],
            occurred_at=event.occurred_at,
        )
        for event in events
    ]
    supplements = list(
        (
            await session.scalars(
                select(AfterSaleSupplement)
                .where(
                    AfterSaleSupplement.merchant_id == record.merchant_id,
                    AfterSaleSupplement.after_sale_id == record.id,
                )
                .order_by(AfterSaleSupplement.submitted_at, AfterSaleSupplement.id)
            )
        ).all()
    )
    supplement_models = [
        AfterSaleSupplementOut(id=str(item.id), note=item.note, submitted_at=item.submitted_at)
        for item in supplements
    ]
    replies = list(
        (
            await session.scalars(
                select(AfterSaleReply)
                .where(
                    AfterSaleReply.merchant_id == record.merchant_id,
                    AfterSaleReply.after_sale_id == record.id,
                )
                .order_by(AfterSaleReply.sent_at, AfterSaleReply.id)
            )
        ).all()
    )
    reply_models = [
        AfterSaleReplyOut(id=str(item.id), text=item.text, sent_at=item.sent_at) for item in replies
    ]
    base = {
        **to_summary(record).model_dump(),
        "reason": record.reason,
        "lines": line_models,
        "events": event_models,
        "supplements": supplement_models,
        "replies": reply_models,
    }
    if customer:
        return CustomerAfterSaleDetailResponse(
            **base, conversation_summary_shared=record.conversation_summary_status == "AVAILABLE"
        )
    assert alias_secret is not None
    ticket = await session.scalar(
        select(SupportTicket.id).where(
            SupportTicket.merchant_id == record.merchant_id,
            SupportTicket.after_sale_id == record.id,
        )
    )
    assert ticket is not None
    snapshot = ConversationSnapshot(
        status=record.conversation_summary_status,
        text=record.conversation_summary_text,
        unavailable_reason=record.conversation_summary_reason,
    )
    return MerchantAfterSaleDetailResponse(
        **base,
        buyer_alias=buyer_alias(alias_secret, record.merchant_id, record.buyer_key, locale),
        first_response_due_at=record.created_at + timedelta(hours=24),
        ticket_id=str(ticket),
        conversation_summary=snapshot,
    )


async def add_supplement(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    sale_id: str,
    payload: AfterSaleSupplementRequest,
    secret: bytes,
    audits: AuditRepository,
    request_id: str,
    now: datetime,
) -> dict[str, Any]:
    """补充说明与事件、状态投影在同一事务里；网络重试原样回放。"""

    record = await require_owned_sale(
        session,
        ctx=ctx,
        sale_id=sale_id,
        audits=audits,
        request_id=request_id,
        customer=True,
    )
    digest = hashlib.sha256(
        json.dumps(
            {"sale_id": sale_id, "note": payload.note},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    async def execute() -> dict[str, Any]:
        try:
            updated = await transition(
                session,
                merchant_id=ctx.merchant_id,
                after_sale_id=record.id,
                target=AfterSaleState.PENDING_MERCHANT,
                actor=AfterSaleActor.CUSTOMER,
                now=now,
            )
        except IllegalTransition:
            raise IllegalStateTransitionError from None
        session.add(
            AfterSaleSupplement(
                merchant_id=ctx.merchant_id,
                after_sale_id=record.id,
                note=redact_sensitive_text(payload.note),
                submitted_at=now,
            )
        )
        await session.flush()
        await session.refresh(updated)
        return to_summary(updated).model_dump(mode="json")

    return await run_idempotent(
        repo=IdempotencyRepository(session),
        ctx=ctx,
        secret=secret,
        operation="shop.after_sales.supplement",
        client_request_id=payload.client_request_id,
        request_digest=digest,
        response_status=200,
        execute=execute,
    )
