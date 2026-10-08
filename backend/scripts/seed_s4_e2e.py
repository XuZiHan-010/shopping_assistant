"""S4 浏览器验收的一次性已签收订单；只接受专用 _s4_e2e_test 数据库。"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product
from app.models.events import FulfillmentEvent
from app.models.merchant import Merchant
from tests.postgres import TRUNCATE_ALL_TABLES
from tests.support.e2e_s4_app import (
    S4_BUYER_KEY,
    S4_MERCHANT_ID,
    S4_ORDER_ID,
    S4_PRODUCT_ID,
    S4_SHOP_SLUG,
    build_settings,
)


async def main() -> None:
    database_url = os.environ["S4_E2E_DATABASE_URL"]
    if not database_url.rstrip("/").endswith("_s4_e2e_test"):
        raise RuntimeError("S4 种子会清空整库，只接受 _s4_e2e_test 数据库")
    database = Database(build_settings(database_url))
    now = datetime.now(UTC)
    delivered = now - timedelta(days=1)
    try:
        async with database.session() as session:
            await session.execute(text(TRUNCATE_ALL_TABLES))
            session.add(Merchant(
                id=S4_MERCHANT_ID, merchant_code=S4_SHOP_SLUG,
                display_name="Borough商家100",
            ))
            await session.flush()
            session.add(Product(
                id=S4_PRODUCT_ID, merchant_id=S4_MERCHANT_ID,
                business_date=now.date(), product_code="S4-E2E-P001",
                title="S4 验收商品", category="测试类目", price=Decimal("100.00"),
                status="ONLINE", listed_at=now - timedelta(days=20),
                stock_on_hand=20, stock_reserved=0, low_stock_threshold=5,
            ))
            await session.flush()
            session.add(Order(
                id=S4_ORDER_ID, merchant_id=S4_MERCHANT_ID,
                business_date=delivered.date(), order_no="S4-E2E-O001",
                buyer_key=S4_BUYER_KEY, order_status="COMPLETED",
                total_amount=Decimal("100.00"), paid_amount=Decimal("100.00"),
                placed_at=delivered - timedelta(days=1), paid_at=delivered - timedelta(days=1),
                payment_status="PAID", fulfillment_status="DELIVERED",
                after_sale_status="NONE", lifecycle_origin="V2",
            ))
            await session.flush()
            session.add(OrderItem(
                merchant_id=S4_MERCHANT_ID, business_date=delivered.date(),
                order_id=S4_ORDER_ID, product_id=S4_PRODUCT_ID, quantity=1,
                item_amount=Decimal("100.00"), unit_price=Decimal("100.00"),
                discount_amount=Decimal("0.00"), line_total=Decimal("100.00"),
                title_snapshot="S4 验收商品",
            ))
            session.add(FulfillmentEvent(
                merchant_id=S4_MERCHANT_ID, subject_id=S4_ORDER_ID,
                event_type="DELIVERED", occurred_at=delivered,
                dedupe_key=f"s4-delivered:{S4_ORDER_ID}", payload={},
            ))
            await session.commit()
    finally:
        await database.dispose()


if __name__ == "__main__":
    configure_event_loop_policy()
    asyncio.run(main())
