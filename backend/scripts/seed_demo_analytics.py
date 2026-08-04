"""把 180 天演示经营数据写入数据库。

Seed 不属于 Migration（计划 §7.4）：迁移必须永远可复现，而演示数据会随
阶段调整。脚本按商家整体重写，可重复执行。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date

from sqlalchemy import delete

from app.analytics.demo_data import build_demo_dataset
from app.core.config import Settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket
from app.services.seed_service import default_merchants

_DELETE_ORDER = (SupportTicket, ReturnRecord, Refund, OrderItem, Order, Product)


async def _seed(days: int, end_date: date) -> int:
    settings = Settings()  # type: ignore[call-arg]
    database = Database(settings)
    written = 0
    async with database.session() as session:
        for index, merchant in enumerate(default_merchants()):
            for model in _DELETE_ORDER:
                await session.execute(delete(model).where(model.merchant_id == merchant.id))
            dataset = build_demo_dataset(
                merchant_id=merchant.id,
                end_date=end_date,
                days=days,
                seed=20260804 + index,
            )
            for model, rows in (
                (Product, dataset.products),
                (Order, dataset.orders),
                (OrderItem, dataset.order_items),
                (Refund, dataset.refunds),
                (ReturnRecord, dataset.returns),
                (SupportTicket, dataset.tickets),
            ):
                if rows:
                    await session.execute(model.__table__.insert(), rows)
                    written += len(rows)
        await session.commit()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="写入演示经营数据")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    # Windows 的默认事件循环跑不了 psycopg 异步模式，见 app.core.runtime 的说明。
    configure_event_loop_policy()
    total = asyncio.run(_seed(args.days, args.end_date))
    print(f"已写入 {total} 行演示经营数据")


if __name__ == "__main__":
    main()
