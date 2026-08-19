"""把 180 天演示经营数据写入数据库。

Seed 不属于 Migration（计划 §7.4）：迁移必须永远可复现，而演示数据会随
阶段调整。脚本按商家整体重写，可重复执行。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime

from sqlalchemy import delete

from app.analytics.dates import business_today
from app.analytics.demo_data import DEMO_ANALYTICS_SEED_BASE, build_demo_dataset
from app.core.config import AppEnvironment, Settings, get_settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket
from app.services.seed_service import default_merchants

_DELETE_ORDER = (SupportTicket, ReturnRecord, Refund, OrderItem, Order, Product)


def reject_production(settings: Settings) -> None:
    """本脚本开头会 DELETE 掉六张经营表里该商家的**全部**数据再重写。

    与 `scripts/seed_demo_data.py` 同一道护栏：一个填错的 `DATABASE_URL`
    在生产上就是一次破坏性操作，而不是「多了一批演示数据」。
    """

    if settings.app_env is AppEnvironment.PRODUCTION:
        raise RuntimeError("生产环境禁止运行演示 Seed")


def default_end_date(now: datetime, *, timezone: str) -> date:
    """最新一天的 `business_date` 必须按业务时区算，不能用宿主本地日期。

    `business_date` 是写入时按业务时区换算的物理列，全系统只有 Seed 这一处
    写入路径。宿主若跑在 UTC，`date.today()` 在业务日 08:00 之前都比业务今天
    晚一天——「今天的 GMV」会查不到任何数据。
    """

    return business_today(now, timezone=timezone)


async def _seed(days: int, end_date: date) -> int:
    settings = get_settings()
    reject_production(settings)
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
                seed=DEMO_ANALYTICS_SEED_BASE + index,
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
