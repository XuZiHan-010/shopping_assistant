"""写入 S3 浏览器验收所需的隔离数据（`n2-merchant-vue-v2-migration` Task 7）。

一个低库存商品（在库 3、阈值 5 → `LOW_STOCK`）加两笔近 30 天的已付款订单，
让可售天数是确定值而不是「未知」。订单直接写入，**不走结账**——S3 前五步
不依赖模块 B；「顾客端公开接口确认档位恢复」那一步等模块 B 落地后再补。

每次运行先清空整库再播种，所以只允许连接专用的 `*_s3_e2e_test` 库。
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product
from app.models.merchant import Merchant
from tests.postgres import TRUNCATE_ALL_TABLES
from tests.support.e2e_s3_app import (
    S3_MERCHANT_ID,
    S3_PRODUCT_ID,
    S3_PRODUCT_TITLE,
    build_settings,
)

UNIT_PRICE = Decimal("100.00")
ON_HAND = 3
LOW_STOCK_THRESHOLD = 5


async def main() -> None:
    database_url = os.environ["S3_E2E_DATABASE_URL"]
    if not database_url.rstrip("/").endswith("_s3_e2e_test"):
        raise RuntimeError("S3 浏览器验收会清空整库，只能连接名称以 _s3_e2e_test 结尾的数据库")

    database = Database(build_settings(database_url))
    now = datetime.now(UTC)
    try:
        async with database.session() as session:
            await session.execute(text(TRUNCATE_ALL_TABLES))
            session.add(
                Merchant(
                    id=S3_MERCHANT_ID,
                    merchant_code="borough-s3-e2e",
                    display_name="Borough商家100",
                )
            )
            await session.flush()
            listed_at = now - timedelta(days=400)
            session.add(
                Product(
                    id=S3_PRODUCT_ID,
                    merchant_id=S3_MERCHANT_ID,
                    business_date=listed_at.date(),
                    product_code="S3-E2E-P001",
                    title=S3_PRODUCT_TITLE,
                    category="测试类目",
                    price=UNIT_PRICE,
                    status="ONLINE",
                    listed_at=listed_at,
                    stock_on_hand=ON_HAND,
                    stock_reserved=0,
                    low_stock_threshold=LOW_STOCK_THRESHOLD,
                )
            )
            await session.flush()
            for index, days_ago in enumerate((1, 3)):
                await _add_paid_order(session, index, now - timedelta(days=days_ago), quantity=5)
            await session.commit()
    finally:
        await database.dispose()


async def _add_paid_order(
    session: AsyncSession, index: int, moment: datetime, *, quantity: int
) -> None:
    """库存告警的销量口径只认已付款订单。"""

    line_total = UNIT_PRICE * quantity
    order = Order(
        merchant_id=S3_MERCHANT_ID,
        business_date=moment.date(),
        order_no=f"S3-E2E-O{index + 1:03d}",
        buyer_key="s3-e2e-buyer",
        order_status="PAID",
        total_amount=line_total,
        paid_amount=line_total,
        placed_at=moment,
        paid_at=moment,
        payment_status="PAID",
        fulfillment_status="NOT_SHIPPED",
        lifecycle_origin="V2",
    )
    session.add(order)
    await session.flush()
    session.add(
        OrderItem(
            merchant_id=S3_MERCHANT_ID,
            business_date=moment.date(),
            order_id=order.id,
            product_id=S3_PRODUCT_ID,
            quantity=quantity,
            item_amount=line_total,
            unit_price=UNIT_PRICE,
            discount_amount=Decimal("0.00"),
            line_total=line_total,
        )
    )


if __name__ == "__main__":
    configure_event_loop_policy()
    asyncio.run(main())
