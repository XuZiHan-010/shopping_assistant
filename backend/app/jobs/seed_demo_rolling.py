"""以事务和双重护栏维护专用演示库的滚动经营数据。"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.dates import business_today
from app.analytics.demo_data import (
    DEMO_ANALYTICS_SEED_BASE,
    build_demo_catalog,
    build_demo_dataset,
)
from app.core.runtime import configure_event_loop_policy
from app.core.seed_config import SeedSettings
from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord, SupportTicket
from app.models.merchant import Merchant
from app.services.seed_service import default_merchants

ADVISORY_LOCK_ID = 2026081801
DEFAULT_WINDOW_DAYS = 180


def require_demo_refresh_permission(settings: SeedSettings) -> None:
    if not settings.allow_demo_data_refresh:
        raise RuntimeError("未启用 ALLOW_DEMO_DATA_REFRESH，拒绝修改演示数据")


async def _require_demo_merchants(session: AsyncSession) -> None:
    actual = set(await session.scalars(select(Merchant.id)))
    expected = {merchant.id for merchant in default_merchants()}
    if actual != expected:
        raise RuntimeError("仅允许写入专用演示数据库：商家集合不匹配")


async def _catalog(session: AsyncSession, merchant_id: UUID, seed: int) -> list[dict[str, object]]:
    generated = build_demo_catalog(merchant_id=merchant_id, seed=seed)
    statement = (
        insert(Product)
        .values(generated)
        .on_conflict_do_nothing(index_elements=[Product.merchant_id, Product.product_code])
    )
    await session.execute(statement)
    persisted = list(
        (await session.execute(select(Product.__table__).where(Product.merchant_id == merchant_id)))
        .mappings()
        .all()
    )
    return [dict(row) for row in sorted(persisted, key=lambda row: str(row["product_code"]))]


async def roll_forward(
    session: AsyncSession,
    *,
    settings: SeedSettings,
    business_day: date,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> int:
    """补齐所有漏跑日，并仅清理窗口外的经营事实。"""

    require_demo_refresh_permission(settings)
    written = 0
    # 调用方可能已经开着事务（集成测试的 fixture 先落了商家行就是这种情况），
    # 此时 `session.begin()` 会直接抛 InvalidRequestError。已有事务就并入它，
    # 由调用方决定提交时机；没有才自己开——两种情况下"校验+追加+清理"都在同一事务里。
    async with nullcontext() if session.in_transaction() else session.begin():
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": ADVISORY_LOCK_ID}
        )
        await _require_demo_merchants(session)
        for index, merchant in enumerate(default_merchants()):
            latest = await session.scalar(
                select(func.max(Order.business_date)).where(Order.merchant_id == merchant.id)
            )
            start = (
                latest + timedelta(days=1)
                if latest is not None
                else business_day - timedelta(days=window_days - 1)
            )
            catalog = await _catalog(session, merchant.id, DEMO_ANALYTICS_SEED_BASE + index)
            for day_offset in range((business_day - start).days + 1):
                day = start + timedelta(days=day_offset)
                dataset = build_demo_dataset(
                    merchant_id=merchant.id,
                    end_date=day,
                    days=1,
                    seed=DEMO_ANALYTICS_SEED_BASE + index,
                    catalog=catalog,
                )
                for model, rows in (
                    (Order, dataset.orders),
                    (OrderItem, dataset.order_items),
                    (Refund, dataset.refunds),
                    (ReturnRecord, dataset.returns),
                    (SupportTicket, dataset.tickets),
                ):
                    if rows:
                        await session.execute(insert(model).values(rows))
                        written += len(rows)
            cutoff = business_day - timedelta(days=window_days - 1)
            for model in (SupportTicket, ReturnRecord, Refund, OrderItem, Order):
                await session.execute(
                    delete(model).where(
                        model.merchant_id == merchant.id, model.business_date < cutoff
                    )
                )
    return written


async def _main_async(args: argparse.Namespace) -> int:
    settings = SeedSettings()
    database = Database(settings)
    try:
        target_day = args.business_day or business_today(
            datetime.now(UTC), timezone=settings.business_timezone
        )
        async with database.session() as session:
            written = await roll_forward(
                session, settings=settings, business_day=target_day, window_days=args.window_days
            )
        print(f"演示数据滚动完成：补齐至 {target_day}，已追加 {written} 行")
        return written
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="增量滚动专用演示经营数据，不会重建历史。")
    parser.add_argument(
        "--business-day", type=date.fromisoformat, help="目标业务日，默认按业务时区取今天"
    )
    parser.add_argument(
        "--window-days", type=int, default=DEFAULT_WINDOW_DAYS, help="保留事实窗口天数"
    )
    args = parser.parse_args()
    configure_event_loop_policy()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
