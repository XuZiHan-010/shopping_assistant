"""状态投影与事件账本在真实 PostgreSQL 的同一事务内推进。"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.after_sales import AfterSale
from app.models.analytics import Order
from app.models.events import AfterSaleEvent
from app.schemas.v2.after_sales import AfterSaleActor, AfterSaleState
from app.services.v2.after_sale_machine import IllegalTransition, transition

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


async def sale(session: AsyncSession, merchant_id: UUID, *, kind: str = "TICKET") -> AfterSale:
    order = Order(
        merchant_id=merchant_id,
        business_date=NOW.date(),
        order_no=f"test-{uuid4().hex[:12]}",
        buyer_key="demo-buyer-1",
        order_status="PAID",
        total_amount=Decimal("10.00"),
        paid_amount=Decimal("10.00"),
        placed_at=NOW,
        paid_at=NOW,
        payment_status="PAID",
        fulfillment_status="NOT_SHIPPED",
        after_sale_status="ACTIVE",
        lifecycle_origin="V2",
    )
    session.add(order)
    await session.flush()
    record = AfterSale(
        merchant_id=merchant_id,
        buyer_key=order.buyer_key,
        order_id=order.id,
        after_sale_type=kind,
        state="PENDING_MERCHANT",
        reason="测试工单",
        refund_amount=None if kind == "TICKET" else Decimal("10.00"),
        state_version=1,
    )
    session.add(record)
    await session.flush()
    session.add(
        AfterSaleEvent(
            merchant_id=merchant_id,
            subject_id=record.id,
            event_type="PENDING_MERCHANT",
            occurred_at=NOW,
            dedupe_key=f"after-sale:{record.id}:1",
            payload={"from_state": None, "to_state": "PENDING_MERCHANT", "actor": "CUSTOMER"},
        )
    )
    await session.flush()
    return record


@pytest.mark.asyncio
async def test_approved_ticket_closes_with_two_events_and_order_projection(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    record = await sale(db_session, merchant_one_id)
    await transition(
        db_session, merchant_id=merchant_one_id, after_sale_id=record.id,
        target=AfterSaleState.APPROVED, actor=AfterSaleActor.MERCHANT, now=NOW,
    )
    await db_session.flush()
    events = list((await db_session.scalars(
        select(AfterSaleEvent).where(AfterSaleEvent.subject_id == record.id)
        .order_by(AfterSaleEvent.occurred_at, AfterSaleEvent.id)
    )).all())
    assert [(event.event_type, event.payload["actor"]) for event in events] == [
        ("PENDING_MERCHANT", "CUSTOMER"), ("APPROVED", "MERCHANT"), ("CLOSED", "SYSTEM")
    ]
    assert record.state == "CLOSED" and record.state_version == 3
    assert (await db_session.get(Order, record.order_id)).after_sale_status == "CLOSED"


@pytest.mark.asyncio
async def test_48th_information_request_does_not_write_event(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    record = await sale(db_session, merchant_one_id)
    for index in range(47):
        db_session.add(
            AfterSaleEvent(
                merchant_id=merchant_one_id, subject_id=record.id,
                event_type="AWAITING_CUSTOMER_INFO", occurred_at=NOW,
                dedupe_key=f"after-sale:{record.id}:request:{index}",
                payload={
                    "from_state": "PENDING_MERCHANT",
                    "to_state": "AWAITING_CUSTOMER_INFO",
                    "actor": "MERCHANT",
                },
            )
        )
    await db_session.flush()
    count_query = select(func.count()).select_from(AfterSaleEvent).where(
        AfterSaleEvent.subject_id == record.id
    )
    before = await db_session.scalar(count_query)
    with pytest.raises(IllegalTransition):
        await transition(
            db_session, merchant_id=merchant_one_id, after_sale_id=record.id,
            target=AfterSaleState.AWAITING_CUSTOMER_INFO, actor=AfterSaleActor.MERCHANT, now=NOW,
        )
    after = await db_session.scalar(count_query)
    assert after == before and record.state == "PENDING_MERCHANT"
