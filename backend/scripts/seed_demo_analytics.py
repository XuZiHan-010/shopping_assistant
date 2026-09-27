"""把 180 天演示经营数据写入数据库。

Seed 不属于 Migration（计划 §7.4）：迁移必须永远可复现，而演示数据会随
阶段调整。脚本按商家整体重写，可重复执行，且仅允许连接本机或本地 Compose 数据库；
线上经营数据唯一写入口为 `app.jobs.seed_demo_rolling` Cron。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.dates import business_today
from app.analytics.demo_data import DEMO_ANALYTICS_SEED_BASE, build_demo_dataset
from app.analytics.seed_safety import assert_local_database_url, reject_production
from app.core.config import get_settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.jobs.seed_demo_rolling import _require_demo_merchants
from app.models.after_sales import AfterSale, AfterSaleLine
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket
from app.models.drafts import ChangeLedger, Draft
from app.models.events import FulfillmentEvent, InventoryEvent
from app.models.memory_v2 import CustomerSignal, DailyBrief
from app.models.promotion import Coupon
from app.services.seed_service import default_merchants


def default_end_date(now: datetime, *, timezone: str) -> date:
    """最新一天的 `business_date` 必须按业务时区算，不能用宿主本地日期。

    `business_date` 是写入时按业务时区换算的物理列，全系统只有 Seed 这一处
    写入路径。宿主若跑在 UTC，`date.today()` 在业务日 08:00 之前都比业务今天
    晚一天——「今天的 GMV」会查不到任何数据。
    """

    return business_today(now, timezone=timezone)


async def seed_analytics(session: AsyncSession, *, days: int, end_date: date) -> int:
    """全量重灌只面向三商家专用库，先检查商家集合，再改写任何事实。"""

    await _require_demo_merchants(session)
    if days < 1:
        raise ValueError("days 必须大于 0")
    # 事件账本拒绝 DELETE；本地专用库经三商家精确校验后，可显式 TRUNCATE 重建。
    await session.execute(
        text("TRUNCATE TABLE after_sale_events, fulfillment_events, inventory_events")
    )
    for model in (ChangeLedger, Draft, Coupon, DailyBrief, CustomerSignal):
        await session.execute(delete(model))
    for model in (SupportTicket, ReturnRecord, Refund, AfterSaleLine, AfterSale):
        await session.execute(delete(model))
    written = 0
    for index, merchant in enumerate(default_merchants()):
        for model in (OrderItem, Order, Product):
            await session.execute(delete(model).where(model.merchant_id == merchant.id))
        dataset = build_demo_dataset(
            merchant_id=merchant.id,
            end_date=end_date,
            days=days,
            seed=DEMO_ANALYTICS_SEED_BASE + index,
        )
        for model, rows in (
            (Product, dataset.products),
            (Order, dataset.orders),
            (OrderItem, dataset.order_items),
            (Refund, dataset.refunds),
            (ReturnRecord, dataset.returns),
            (SupportTicket, dataset.tickets),
            (InventoryEvent, dataset.inventory_events),
            (FulfillmentEvent, dataset.fulfillment_events),
        ):
            if rows:
                await session.execute(model.__table__.insert(), rows)
                written += len(rows)
    return written


async def _seed(days: int, end_date: date) -> int:
    settings = get_settings()
    assert_local_database_url(settings.database_url)
    reject_production(settings)
    database = Database(settings)
    try:
        async with database.session() as session:
            written = await seed_analytics(session, days=days, end_date=end_date)
            await session.commit()
        return written
    finally:
        await database.dispose()


def _dry_run(days: int, end_date: date) -> None:
    """只跑纯生成逻辑并报数，绝不连数据库——所以它也不需要生产护栏。"""

    total = 0
    for index, merchant in enumerate(default_merchants()):
        dataset = build_demo_dataset(
            merchant_id=merchant.id,
            end_date=end_date,
            days=days,
            seed=DEMO_ANALYTICS_SEED_BASE + index,
        )
        rows = sum(
            len(part)
            for part in (
                dataset.products,
                dataset.orders,
                dataset.order_items,
                dataset.refunds,
                dataset.returns,
                dataset.tickets,
                dataset.inventory_events,
                dataset.fulfillment_events,
            )
        )
        total += rows
        print(f"- {merchant.merchant_code}: {rows} 行")
    print(f"计划覆盖 {days} 天、截止业务日 {end_date}，先删除既有数据再写入共 {total} 行。")


def main() -> None:
    parser = argparse.ArgumentParser(description="写入演示经营数据")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="最新一天的业务日；默认取业务时区的今天",
    )
    parser.add_argument("--dry-run", action="store_true", help="只展示计划，不写数据库")
    parser.add_argument(
        "--force-full-rebuild",
        action="store_true",
        help="明确确认删除全部演示经营历史后重建",
    )
    args = parser.parse_args()
    end_date = args.end_date or default_end_date(
        datetime.now(UTC), timezone=get_settings().business_timezone
    )
    if args.dry_run:
        _dry_run(args.days, end_date)
        return
    if not args.force_full_rebuild:
        parser.error(
            "演示数据现在由 app.jobs.seed_demo_rolling 每日滚动维护；"
            "全量重灌会抹掉历史，需显式传入 --force-full-rebuild"
        )
    # Windows 的默认事件循环跑不了 psycopg 异步模式，见 app.core.runtime 的说明。
    configure_event_loop_policy()
    total = asyncio.run(_seed(args.days, end_date))
    print(f"已写入 {total} 行演示经营数据")


if __name__ == "__main__":
    main()
