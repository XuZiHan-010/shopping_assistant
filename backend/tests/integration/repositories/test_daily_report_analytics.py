"""日报聚合必须在真实 PostgreSQL 上验证口径、日期边界和商家隔离。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket
from app.repositories.analytics import AnalyticsRepository

REPORT_DATE = date(2026, 8, 20)
NOW = datetime(2026, 8, 21, 1, tzinfo=UTC)


async def _product(session: AsyncSession, merchant_id: UUID) -> Product:
    product = Product(
        merchant_id=merchant_id,
        business_date=REPORT_DATE,
        product_code=f"SKU-{uuid4().hex[:8]}",
        title="日报测试商品",
        category="女装",
        price=Decimal("100.00"),
        status="ONLINE",
        listed_at=NOW,
    )
    session.add(product)
    await session.flush()
    return product


async def _order(
    session: AsyncSession,
    *,
    merchant_id: UUID,
    product_id: UUID,
    business_date: date,
    buyer_key: str,
    status: str,
    paid_amount: Decimal,
) -> OrderItem:
    order = Order(
        merchant_id=merchant_id,
        business_date=business_date,
        order_no=f"ORDER-{uuid4().hex[:12]}",
        buyer_key=buyer_key,
        order_status=status,
        total_amount=paid_amount if paid_amount else Decimal("30.00"),
        paid_amount=paid_amount,
        placed_at=NOW,
        paid_at=NOW if paid_amount else None,
    )
    session.add(order)
    await session.flush()
    item = OrderItem(
        merchant_id=merchant_id,
        business_date=business_date,
        order_id=order.id,
        product_id=product_id,
        quantity=1,
        item_amount=paid_amount,
    )
    session.add(item)
    await session.flush()
    return item


async def _seed_report_data(session: AsyncSession, merchant_id: UUID) -> None:
    product = await _product(session, merchant_id)
    completed = await _order(
        session,
        merchant_id=merchant_id,
        product_id=product.id,
        business_date=REPORT_DATE,
        buyer_key="buyer-a",
        status="COMPLETED",
        paid_amount=Decimal("120.00"),
    )
    await _order(
        session,
        merchant_id=merchant_id,
        product_id=product.id,
        business_date=REPORT_DATE,
        buyer_key="buyer-a",
        status="CREATED",
        paid_amount=Decimal("0.00"),
    )
    await _order(
        session,
        merchant_id=merchant_id,
        product_id=product.id,
        business_date=REPORT_DATE,
        buyer_key="buyer-b",
        status="SHIPPED",
        paid_amount=Decimal("80.00"),
    )
    session.add_all(
        [
            Refund(
                merchant_id=merchant_id,
                business_date=REPORT_DATE,
                order_item_id=completed.id,
                refund_amount=Decimal("50.00"),
                refund_reason="尺码不合适",
                refund_status="REFUNDED",
                refunded_at=NOW,
            ),
            ReturnRecord(
                merchant_id=merchant_id,
                business_date=REPORT_DATE,
                order_item_id=completed.id,
                return_quantity=2,
                return_reason="尺码不合适",
                return_status="COMPLETED",
                logistics_status="DELIVERED",
                returned_at=NOW,
            ),
            SupportTicket(
                merchant_id=merchant_id,
                business_date=REPORT_DATE,
                ticket_no=f"TICKET-{uuid4().hex[:8]}",
                order_id=completed.order_id,
                ticket_status="OPEN",
                ticket_reason="物流咨询",
                opened_at=NOW,
            ),
        ]
    )

    # 近七日数据用于建议，不得把报表日以外的数据混进昨日六项指标。
    prior_day = REPORT_DATE - timedelta(days=3)
    prior_item = await _order(
        session,
        merchant_id=merchant_id,
        product_id=product.id,
        business_date=prior_day,
        buyer_key="buyer-c",
        status="COMPLETED",
        paid_amount=Decimal("40.00"),
    )
    session.add(
        Refund(
            merchant_id=merchant_id,
            business_date=prior_day,
            order_item_id=prior_item.id,
            refund_amount=Decimal("20.00"),
            refund_reason="质量问题",
            refund_status="REFUNDED",
            refunded_at=NOW,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_daily_report_aggregates_fixed_metrics_and_isolates_merchants(
    db_session: AsyncSession,
    merchant_one_id: UUID,
    merchant_two_id: UUID,
) -> None:
    await _seed_report_data(db_session, merchant_one_id)
    await _seed_report_data(db_session, merchant_two_id)
    repository = AnalyticsRepository(db_session)

    metrics = await repository.daily_report_metrics(
        merchant_id=merchant_one_id,
        report_date=REPORT_DATE,
    )
    signals = await repository.recent_daily_report_signals(
        merchant_id=merchant_one_id,
        report_date=REPORT_DATE,
    )

    assert metrics == {
        "gmv": Decimal("200.00"),
        "ordering_user_count": 2,
        "order_count": 3,
        "successful_order_count": 1,
        "return_count": 2,
        "refund_amount": Decimal("50.00"),
    }
    assert isinstance(metrics["gmv"], Decimal)
    assert isinstance(metrics["refund_amount"], Decimal)
    assert signals.has_data is True
    assert signals.refund_amount == Decimal("70.00")
    assert signals.order_count == 4
    assert signals.ticket_count == 1
