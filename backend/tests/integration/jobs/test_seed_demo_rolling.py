from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.seed_config import SeedSettings
from app.jobs.seed_demo_rolling import roll_forward
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord
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
async def test_rolling_seed_keeps_a_refund_still_in_window_even_if_its_order_left_it(
    db_session: AsyncSession,
) -> None:
    """旧脚本曾让退款日期比订单晚最多 5 天。订单本身可能已经滑出窗口，但那笔
    退款的业务日期还在窗口内——它不该被「删订单」的级联外键顺手带走。"""

    await seed_demo_merchants(db_session, default_merchants())
    merchant = default_merchants()[0]

    # 这几张表之间只有裸 `ForeignKey`，没有声明 ORM `relationship()`，flush 时
    # SQLAlchemy 不会按外键拓扑排序插入顺序；逐条 flush 以显式保证父行先落库。
    product_id = uuid4()
    db_session.add(
        Product(
            id=product_id,
            merchant_id=merchant.id,
            business_date=date(2026, 8, 10),
            product_code="legacy-lag-sku",
            title="历史滞后退款商品",
            category="其他",
            price=Decimal("100.00"),
            status="ONLINE",
            listed_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
    )
    await db_session.flush()

    order_id = uuid4()
    db_session.add(
        Order(
            id=order_id,
            merchant_id=merchant.id,
            business_date=date(2026, 8, 10),  # 早于下方 cutoff（8/15），本该被清理
            order_no="legacy-lag-order",
            buyer_key="legacy-buyer",
            address_city_name=None,
            order_status="COMPLETED",
            total_amount=Decimal("100.00"),
            paid_amount=Decimal("100.00"),
            placed_at=datetime(2026, 8, 10, tzinfo=UTC),
            paid_at=datetime(2026, 8, 10, tzinfo=UTC),
        )
    )
    await db_session.flush()

    order_item_id = uuid4()
    db_session.add(
        OrderItem(
            id=order_item_id,
            merchant_id=merchant.id,
            business_date=date(2026, 8, 10),
            order_id=order_id,
            product_id=product_id,
            quantity=1,
            item_amount=Decimal("100.00"),
        )
    )
    await db_session.flush()

    refund_id = uuid4()
    db_session.add(
        Refund(
            id=refund_id,
            merchant_id=merchant.id,
            business_date=date(2026, 8, 16),  # 晚于订单 6 天，仍在下方窗口内
            order_item_id=order_item_id,
            refund_amount=Decimal("100.00"),
            refund_reason="旧脚本跨天滞后场景",
            refund_status="REFUNDED",
            refunded_at=datetime(2026, 8, 16, tzinfo=UTC),
        )
    )
    await db_session.flush()

    # business_day=2026-08-19、window_days=5 → cutoff=2026-08-15：
    # 订单/订单项的 8/10 在窗口外，退款的 8/16 仍在窗口内。
    await roll_forward(
        db_session, settings=_settings(), business_day=date(2026, 8, 19), window_days=5
    )

    assert await db_session.get(Refund, refund_id) is not None, "仍在窗口内的退款不该被级联删除"
    kept_item = await db_session.get(OrderItem, order_item_id)
    assert kept_item is not None, "被在窗口内退款引用的订单项不该被删除"
    kept_order = await db_session.get(Order, order_id)
    assert kept_order is not None, "被在窗口内订单项引用的订单不该被删除"
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
