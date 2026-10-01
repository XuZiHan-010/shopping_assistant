"""商家售后草稿应用时复核状态，并把退款和回补写入真实 PostgreSQL。"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import VersionConflictError
from app.core.session import SessionContext, SessionRole
from app.models.after_sales import AfterSale, AfterSaleLine, AfterSaleReply
from app.models.analytics import OrderItem, Product, Refund, ReturnRecord
from app.models.drafts import Draft
from app.models.events import InventoryEvent
from app.services.v2.after_sales import sale_detail
from app.services.v2.draft_handlers import HandlerRequest
from app.services.v2.draft_handlers.after_sale_decision import AfterSaleDecisionHandler
from tests.integration.v2.test_after_sale_machine import NOW, sale

pytestmark = pytest.mark.integration
# UTC 9/24 20:00 = 上海 9/25 04:00：退款、退货必须记在业务日，净成交额才与首页同日。
CROSS_DAY = datetime(2026, 9, 24, 20, tzinfo=UTC)


def context(merchant_id: UUID) -> SessionContext:
    return SessionContext(
        session_record_id=uuid4(),
        role=SessionRole.MERCHANT,
        merchant_id=merchant_id,
        buyer_key=None,
        shop_slug=None,
    )


async def draft(
    session: AsyncSession,
    merchant_id: UUID,
    sale_id: UUID,
    *,
    version: int,
    decision: str,
    sellable: bool | None = None,
    reply_text: str | None = None,
) -> Draft:
    payload: dict[str, object] = {"decision": decision}
    if decision == "REJECT":
        payload["rule_reference"] = "平台演示售后规则 §3.2"
    if sellable is not None:
        payload["sellable"] = sellable
    if reply_text is not None:
        payload["reply_text"] = reply_text
    record = Draft(
        merchant_id=merchant_id,
        kind="AFTER_SALE_DECISION",
        title="售后决定",
        target_type="AFTER_SALE",
        target_id=sale_id,
        target_version=version,
        draft_version=1,
        state="STAGED",
        payload=payload,
        guardrail_snapshot={},
        created_by="AGENT",
        expires_at=NOW + timedelta(days=7),
    )
    session.add(record)
    await session.flush()
    return record


async def apply(
    session: AsyncSession, merchant_id: UUID, record: Draft, *, now: datetime = NOW
) -> None:
    await AfterSaleDecisionHandler().apply(
        session,
        context(merchant_id),
        record,
        HandlerRequest(
            draft_version=1, target_version=record.target_version, accepted_entry_ids=None
        ),
        now=now,
        locale="zh-CN",  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_ticket_approval_auto_closes_and_stale_draft_is_rejected(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    record = await sale(db_session, merchant_one_id)
    proposal = await draft(
        db_session, merchant_one_id, record.id, version=record.state_version, decision="APPROVE"
    )
    await apply(db_session, merchant_one_id, proposal)
    assert record.state == "CLOSED"
    stale = await draft(db_session, merchant_one_id, record.id, version=1, decision="REJECT")
    with pytest.raises(VersionConflictError):
        await apply(db_session, merchant_one_id, stale)


@pytest.mark.asyncio
async def test_approved_reply_is_delivered_atomically_to_customer_detail(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    record = await sale(db_session, merchant_one_id)
    proposal = await draft(
        db_session,
        merchant_one_id,
        record.id,
        version=record.state_version,
        decision="APPROVE",
        reply_text="已为您处理。",
    )
    await apply(db_session, merchant_one_id, proposal)
    reply = await db_session.scalar(
        select(AfterSaleReply).where(
            AfterSaleReply.merchant_id == merchant_one_id,
            AfterSaleReply.after_sale_id == record.id,
        )
    )
    assert reply is not None and reply.draft_id == proposal.id
    await db_session.refresh(record)
    detail = await sale_detail(db_session, record, customer=True)
    assert [item.text for item in detail.replies] == ["已为您处理。"]


@pytest.mark.asyncio
async def test_reply_write_failure_rolls_back_decision(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    record = await sale(db_session, merchant_one_id)
    sale_id = record.id
    proposal = await draft(
        db_session,
        merchant_one_id,
        record.id,
        version=record.state_version,
        decision="APPROVE",
        reply_text="已受理。",
    )
    db_session.add(
        AfterSaleReply(
            merchant_id=merchant_one_id,
            after_sale_id=record.id,
            draft_id=proposal.id,
            text="预占唯一键以模拟送达失败",
            sent_at=NOW,
        )
    )
    await db_session.commit()
    with pytest.raises(IntegrityError):
        await apply(db_session, merchant_one_id, proposal)
    await db_session.rollback()
    unchanged = await db_session.get(AfterSale, sale_id)
    assert unchanged is not None and unchanged.state == "PENDING_MERCHANT"
    assert unchanged.state_version == 1


@pytest.mark.asyncio
async def test_return_receipt_restocks_only_sellable_and_refund_uses_snapshot(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    record = await sale(db_session, merchant_one_id, kind="RETURN_REFUND")
    product = Product(
        merchant_id=merchant_one_id,
        business_date=NOW.date(),
        product_code=f"test-{uuid4().hex[:10]}",
        title="退货商品",
        category="测试",
        price=Decimal("10.00"),
        status="ONLINE",
        listed_at=NOW,
        stock_on_hand=5,
        stock_reserved=0,
    )
    db_session.add(product)
    await db_session.flush()
    item = OrderItem(
        merchant_id=merchant_one_id,
        business_date=NOW.date(),
        order_id=record.order_id,
        product_id=product.id,
        quantity=1,
        item_amount=Decimal("10.00"),
        unit_price=Decimal("10.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("10.00"),
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        AfterSaleLine(
            after_sale_id=record.id,
            order_item_id=item.id,
            quantity=1,
            refund_amount=Decimal("10.00"),
        )
    )
    await db_session.flush()
    await apply(
        db_session,
        merchant_one_id,
        await draft(db_session, merchant_one_id, record.id, version=1, decision="APPROVE"),
    )
    assert record.state == "AWAITING_RETURN"
    await apply(
        db_session,
        merchant_one_id,
        await draft(
            db_session,
            merchant_one_id,
            record.id,
            version=record.state_version,
            decision="RECEIVE",
            sellable=True,
        ),
    )
    assert record.state == "RECEIVED" and product.stock_on_hand == 6
    inventory = await db_session.scalar(
        select(InventoryEvent).where(
            InventoryEvent.subject_id == product.id,
            InventoryEvent.event_type == "RETURN_RESTOCK",
        )
    )
    assert inventory is not None and inventory.payload["delta"] == 1
    db_session.add(
        Refund(
            merchant_id=merchant_one_id,
            business_date=NOW.date(),
            order_item_id=item.id,
            after_sale_id=None,
            refund_amount=Decimal("3.00"),
            refund_reason="PREVIOUS",
            refund_status="REFUNDED",
            refunded_at=NOW,
        )
    )
    await db_session.flush()
    await apply(
        db_session,
        merchant_one_id,
        await draft(
            db_session,
            merchant_one_id,
            record.id,
            version=record.state_version,
            decision="REFUND",
        ),
    )
    assert record.state == "CLOSED"
    refund = await db_session.scalar(select(Refund).where(Refund.after_sale_id == record.id))
    assert refund is not None and refund.refund_amount == Decimal("7.00")
    assert record.refund_amount == Decimal("7.00")
    line = await db_session.scalar(
        select(AfterSaleLine).where(AfterSaleLine.after_sale_id == record.id)
    )
    assert line is not None and line.refund_amount == Decimal("7.00")


@pytest.mark.asyncio
async def test_refund_and_return_use_business_day_across_utc_midnight(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    record = await sale(db_session, merchant_one_id, kind="RETURN_REFUND")
    product = Product(
        merchant_id=merchant_one_id, business_date=NOW.date(),
        product_code=f"test-{uuid4().hex[:10]}", title="退货商品", category="测试",
        price=Decimal("10.00"), status="ONLINE", listed_at=NOW,
        stock_on_hand=5, stock_reserved=0,
    )
    db_session.add(product)
    await db_session.flush()
    item = OrderItem(
        merchant_id=merchant_one_id, business_date=NOW.date(), order_id=record.order_id,
        product_id=product.id, quantity=1, item_amount=Decimal("10.00"),
        unit_price=Decimal("10.00"), discount_amount=Decimal("0.00"),
        line_total=Decimal("10.00"),
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(AfterSaleLine(
        after_sale_id=record.id, order_item_id=item.id, quantity=1,
        refund_amount=Decimal("10.00"),
    ))
    await db_session.flush()
    for decision, sellable in (("APPROVE", None), ("RECEIVE", False), ("REFUND", None)):
        proposal = await draft(
            db_session, merchant_one_id, record.id,
            version=record.state_version, decision=decision, sellable=sellable,
        )
        await apply(db_session, merchant_one_id, proposal, now=CROSS_DAY)

    refund = await db_session.scalar(select(Refund).where(Refund.after_sale_id == record.id))
    returned = await db_session.scalar(
        select(ReturnRecord).where(ReturnRecord.after_sale_id == record.id)
    )
    assert refund is not None and refund.business_date == date(2026, 9, 25)
    assert returned is not None and returned.business_date == date(2026, 9, 25)
