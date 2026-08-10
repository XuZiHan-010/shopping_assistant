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
from app.models.analytics import Order
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
            delete(Order).where(Order.merchant_id.in_([MERCHANT_ID, MERCHANT_ID_B]))
        )
        for merchant_id, code, name in (
            (MERCHANT_ID, "borough-f4-e2e", "Borough商家100"),
            (MERCHANT_ID_B, "borough-f4-e2e-b", "Borough商家101"),
        ):
            if await session.get(Merchant, merchant_id) is None:
                session.add(Merchant(id=merchant_id, merchant_code=code, display_name=name))
        await session.flush()
        session.add_all(
            [
                _order(MERCHANT_ID, "F4-E2E-001", date(2026, 8, 1), "120.50"),
                _order(MERCHANT_ID, "F4-E2E-002", date(2026, 8, 2), "240.00"),
                _order(MERCHANT_ID_B, "F4-E2E-B01", date(2026, 8, 3), "999.99"),
            ]
        )
        await session.commit()
    await database.dispose()


def _order(merchant_id: object, order_no: str, business_date: date, amount: str) -> Order:
    timestamp = datetime.combine(business_date, datetime.min.time(), tzinfo=UTC)
    value = Decimal(amount)
    return Order(
        merchant_id=merchant_id,
        order_no=order_no,
        buyer_key=f"f4-e2e-{order_no}",
        business_date=business_date,
        order_status="PAID",
        total_amount=value,
        paid_amount=value,
        placed_at=timestamp,
        paid_at=timestamp,
    )


if __name__ == "__main__":
    configure_event_loop_policy()
    asyncio.run(main())
