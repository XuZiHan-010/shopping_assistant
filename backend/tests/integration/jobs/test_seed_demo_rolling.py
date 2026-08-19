from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed_config import SeedSettings
from app.jobs.seed_demo_rolling import roll_forward
from app.models.analytics import Order, OrderItem, Refund, ReturnRecord
from app.models.merchant import Merchant
from app.services.seed_service import default_merchants, seed_demo_merchants


def _settings(*, allow: bool = True) -> SeedSettings:
    return SeedSettings(
        database_url="postgresql+psycopg://user:pass@localhost/test",
        allow_demo_data_refresh=allow,
    )


async def _fingerprint_by_day(session: AsyncSession) -> dict[date, tuple[object, ...]]:
    """每个业务日的订单指纹：历史被改写时它一定会变。"""

    rows = (
        await session.execute(
            select(
                Order.business_date,
                func.count(),
                func.sum(Order.total_amount),
                func.min(cast(Order.id, String)),
                func.max(cast(Order.id, String)),
            ).group_by(Order.business_date)
        )
    ).all()
    return {row[0]: tuple(row[1:]) for row in rows}


async def _dangling_foreign_keys(session: AsyncSession) -> int:
    items = select(OrderItem.id)
    refunds = await session.scalar(
        select(func.count()).select_from(Refund).where(Refund.order_item_id.not_in(items))
    )
    returns = await session.scalar(
        select(func.count())
        .select_from(ReturnRecord)
        .where(ReturnRecord.order_item_id.not_in(items))
    )
    orphan_items = await session.scalar(
        select(func.count())
        .select_from(OrderItem)
        .where(OrderItem.order_id.not_in(select(Order.id)))
    )
    return (refunds or 0) + (returns or 0) + (orphan_items or 0)


@pytest.mark.asyncio
async def test_rolling_seed_catches_up_missing_days_and_is_idempotent(
    db_session: AsyncSession,
) -> None:
    """Cron 可能漏跑，也可能因重试跑两次；两种情况都必须收敛到同一结果。"""

    await seed_demo_merchants(db_session, default_merchants())
    await roll_forward(
        db_session, settings=_settings(), business_day=date(2026, 8, 16), window_days=180
    )

    await roll_forward(
        db_session, settings=_settings(), business_day=date(2026, 8, 19), window_days=180
    )
    days = set(await _fingerprint_by_day(db_session))
    snapshot = await _fingerprint_by_day(db_session)

    await roll_forward(
        db_session, settings=_settings(), business_day=date(2026, 8, 19), window_days=180
    )

    assert {date(2026, 8, 17), date(2026, 8, 18), date(2026, 8, 19)} <= days
    assert await _fingerprint_by_day(db_session) == snapshot, "同日重跑必须是 no-op"


@pytest.mark.asyncio
async def test_rolling_seed_never_rewrites_history_and_prunes_the_window(
    db_session: AsyncSession,
) -> None:
    """滚动的全部意义就是历史钉死：昨天回答里的数字，明天必须还是那个数字。"""

    await seed_demo_merchants(db_session, default_merchants())
    await roll_forward(
        db_session, settings=_settings(), business_day=date(2026, 8, 16), window_days=5
    )
    before = await _fingerprint_by_day(db_session)

    await roll_forward(
        db_session, settings=_settings(), business_day=date(2026, 8, 19), window_days=5
    )
    after = await _fingerprint_by_day(db_session)

    for day in set(before) & set(after):
        assert before[day] == after[day], f"{day} 的历史数据被改写了"
    assert date(2026, 8, 19) in after
    assert date(2026, 8, 12) not in after, "滑出 5 天窗口的分区应被清理"
    assert await _dangling_foreign_keys(db_session) == 0


@pytest.mark.asyncio
async def test_rolling_seed_rejects_a_database_with_non_demo_merchants(
    db_session: AsyncSession,
) -> None:
    """多一个真实商家就说明这不是专用演示库，绝不允许在上面删改数据。"""

    await seed_demo_merchants(db_session, default_merchants())
    db_session.add(
        Merchant(
            id=UUID("3f6c1b2a-0000-4000-8000-0000000000ff"),
            merchant_code="real-tenant-001",
            display_name="真实商家",
        )
    )
    await db_session.flush()

    with pytest.raises(RuntimeError, match="仅允许写入专用演示数据库"):
        await roll_forward(
            db_session, settings=_settings(), business_day=date(2026, 8, 19), window_days=180
        )


@pytest.mark.asyncio
async def test_rolling_seed_refuses_without_the_explicit_write_permission(
    db_session: AsyncSession,
) -> None:
    await seed_demo_merchants(db_session, default_merchants())

    with pytest.raises(RuntimeError, match="ALLOW_DEMO_DATA_REFRESH"):
        await roll_forward(
            db_session,
            settings=_settings(allow=False),
            business_day=date(2026, 8, 19),
            window_days=180,
        )

    assert await db_session.scalar(select(func.count()).select_from(Order)) == 0
