"""净成交额类目归因：真实仓储按退款发生日及原订单项类目归属。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.core.security import MerchantContext
from app.db.session import Database
from app.models.analytics import OrderItem, Refund
from app.repositories.analytics import AnalyticsRepository
from app.services.safe_query import SafeQueryService
from app.services.v2.attribution import AttributionService
from tests.conftest import MERCHANT_ONE_ID
from tests.support.merchant_v2 import seed_paid_order, seed_product

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_net_gmv_category_subtracts_refund_from_same_category(
    postgres_app: FastAPI,
) -> None:
    database: Database = postgres_app.state.database
    now = datetime(2026, 9, 23, 12, tzinfo=UTC)
    product_id = await seed_product(database, MERCHANT_ONE_ID, title="归因退款商品")
    current_order = await seed_paid_order(
        database, MERCHANT_ONE_ID, product_id, quantity=3, days_ago=2, now=now
    )
    await seed_paid_order(
        database, MERCHANT_ONE_ID, product_id, quantity=1, days_ago=9, now=now
    )
    async with database.session() as session:
        order_item = await session.scalar(
            select(OrderItem).where(OrderItem.order_id == current_order)
        )
        assert order_item is not None
        session.add(Refund(
            merchant_id=MERCHANT_ONE_ID,
            business_date=(now - timedelta(days=1)).date(),
            order_item_id=order_item.id,
            refund_amount=Decimal("30.00"),
            refund_reason="测试退款", refund_status="REFUNDED",
            refunded_at=now - timedelta(days=1),
        ))
        await session.commit()

    async with database.session() as session:
        service = AttributionService(
            SafeQueryService(AnalyticsRepository(session), business_timezone="UTC")
        )
        result = await service.attribute_change(
            MerchantContext(merchant_id=MERCHANT_ONE_ID),
            metric="net_gmv", dimension="category", today=now,
        )
    assert result.stopped is False
    assert len(result.segments) == 1
    segment = result.segments[0]
    assert segment.current_value == Decimal("270.00")
    assert segment.baseline_value == Decimal("100.00")
