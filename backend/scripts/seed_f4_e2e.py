"""写入 F4 浏览器验收所需的隔离演示订单。"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import delete

from app.core.config import AppEnvironment, Settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product, Refund
from app.models.merchant import Merchant
from tests.support.e2e_app import MERCHANT_ID, MERCHANT_ID_B


async def main() -> None:
    database_url = os.environ["F4_E2E_DATABASE_URL"]
    if not database_url.rstrip("/").endswith("borough_f4_test"):
        raise RuntimeError("F4 浏览器验收只能使用 borough_f4_test 数据库")
    database = Database(
        Settings(
            app_env=AppEnvironment.TEST,
            database_url=database_url,
            frontend_origin="http://127.0.0.1:5274",
        )
    )
    async with database.session() as session:
        await session.execute(
            delete(Refund).where(Refund.merchant_id.in_([MERCHANT_ID, MERCHANT_ID_B]))
        )
        await session.execute(
            delete(OrderItem).where(OrderItem.merchant_id.in_([MERCHANT_ID, MERCHANT_ID_B]))
        )
        await session.execute(
            delete(Order).where(Order.merchant_id.in_([MERCHANT_ID, MERCHANT_ID_B]))
        )
        await session.execute(
            delete(Product).where(Product.merchant_id.in_([MERCHANT_ID, MERCHANT_ID_B]))
        )
        for merchant_id, code, name in (
            (MERCHANT_ID, "borough-f4-e2e", "Borough商家100"),
            (MERCHANT_ID_B, "borough-f4-e2e-b", "Borough商家101"),
        ):
            if await session.get(Merchant, merchant_id) is None:
                session.add(Merchant(id=merchant_id, merchant_code=code, display_name=name))
        await session.flush()
        august_orders = [
            _order(MERCHANT_ID, "F4-E2E-001", date(2026, 8, 1), "120.50"),
            _order(MERCHANT_ID, "F4-E2E-002", date(2026, 8, 2), "240.00"),
            _order(MERCHANT_ID_B, "F4-E2E-B01", date(2026, 8, 3), "999.99"),
        ]
        products = [
            _product(MERCHANT_ID, "F4-E2E-P001", "SPU-F4-001", date(2026, 8, 1)),
            *[
                _product(
                    MERCHANT_ID,
                    f"F4-E2E-P{index + 2:03d}",
                    f"SPU-F4-{index + 2:03d}",
                    date(2026, 7, 1),
                )
                for index in range(201)
            ],
        ]
        july_orders = [
            _order(
                MERCHANT_ID,
                f"F4-E2E-G{index + 1:03d}",
                date(2026, 7, (index % 7) + 1),
                "10.00",
                city=("杭州市", "深圳市", "广州市")[index % 3],
            )
            for index in range(201)
        ]
        session.add_all([*products, *august_orders, *july_orders])
        await session.flush()
        items = [
            OrderItem(
                merchant_id=MERCHANT_ID,
                business_date=date(2026, 8, 1),
                order_id=august_orders[0].id,
                product_id=products[0].id,
                quantity=1,
                item_amount=Decimal("120.50"),
            ),
            OrderItem(
                merchant_id=MERCHANT_ID,
                business_date=date(2026, 8, 2),
                order_id=august_orders[1].id,
                product_id=products[0].id,
                quantity=1,
                item_amount=Decimal("240.00"),
            ),
            *[
                OrderItem(
                    merchant_id=MERCHANT_ID,
                    business_date=order.business_date,
                    order_id=order.id,
                    product_id=products[index + 1].id,
                    quantity=1,
                    item_amount=Decimal("10.00"),
                )
                for index, order in enumerate(july_orders)
            ],
        ]
        session.add_all(items)
        await session.flush()
        session.add(
            Refund(
                merchant_id=MERCHANT_ID,
                business_date=date(2026, 8, 2),
                order_item_id=items[0].id,
                refund_amount=Decimal("12.50"),
                refund_reason="商品破损",
                refund_status="REFUNDED",
                refunded_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        )
        await session.commit()
    await database.dispose()


def _order(
    merchant_id: object,
    order_no: str,
    business_date: date,
    amount: str,
    *,
    city: str | None = None,
) -> Order:
    timestamp = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
    value = Decimal(amount)
    return Order(
        merchant_id=merchant_id,
        order_no=order_no,
        buyer_key=f"f4-e2e-{order_no}",
        business_date=business_date,
        address_city_name=city,
        order_status="PAID",
        total_amount=value,
        paid_amount=value,
        placed_at=timestamp,
        paid_at=timestamp,
    )


def _product(merchant_id: object, product_code: str, spu_id: str, business_date: date) -> Product:
    timestamp = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
    return Product(
        merchant_id=merchant_id,
        business_date=business_date,
        product_code=product_code,
        spu_id=spu_id,
        title=f"E2E 商品 {product_code}",
        category="测试类目",
        price=Decimal("10.00"),
        status="ONLINE",
        listed_at=timestamp,
    )


if __name__ == "__main__":
    configure_event_loop_policy()
    asyncio.run(main())
