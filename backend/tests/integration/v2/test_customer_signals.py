"""同日售后信号按商品聚合；相同售后源重试不重复计数。

内容缺口信号（`CONTENT_GAP`，N3 阶段 C Task 7）与售后信号共用同一张表和同一套聚合思路，
但 `derived_from` 的形状不同：`CustomerSignal` Schema 校验器要求 `CONTENT_GAP` 永远
恰好 1 条 `PRODUCT` 来源（见 `app/schemas/v2/merchant_ops.py` 的 `consistent_signal`），
不能像售后那样累积多条来源历史——`count` 递增但 `derived_from` 只保留"当前这一条"。
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import Product
from app.models.memory_v2 import CustomerSignal
from app.schemas.v2.after_sales import AfterSaleType
from app.services.v2.customer_signals import derive_after_sale_signals, derive_content_gap_signal

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)
# UTC 9/24 20:00 = 上海 9/25 04:00：信号日期必须按业务日记。
CROSS_DAY = datetime(2026, 9, 24, 20, tzinfo=UTC)


@pytest.mark.asyncio
async def test_signal_aggregates_by_product_day_and_source(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    product_id = uuid4()
    db_session.add(Product(
        id=product_id, merchant_id=merchant_one_id, business_date=NOW.date(),
        product_code=f"signal-{product_id.hex[:10]}", title="商品", category="测试",
        price=Decimal("10.00"), status="ONLINE", listed_at=NOW,
        stock_on_hand=1, stock_reserved=0,
    ))
    await db_session.flush()
    first, second = uuid4(), uuid4()
    await derive_after_sale_signals(
        db_session, merchant_id=merchant_one_id,
        kind=AfterSaleType.RETURN_REFUND, sale_id=first,
        products=[(product_id, "商品")], now=NOW,
    )
    await derive_after_sale_signals(
        db_session, merchant_id=merchant_one_id,
        kind=AfterSaleType.RETURN_REFUND, sale_id=first,
        products=[(product_id, "商品")], now=NOW,
    )
    await derive_after_sale_signals(
        db_session, merchant_id=merchant_one_id,
        kind=AfterSaleType.RETURN_REFUND, sale_id=second,
        products=[(product_id, "商品")], now=NOW,
    )
    rows = list((await db_session.scalars(select(CustomerSignal).where(
        CustomerSignal.merchant_id == merchant_one_id
    ))).all())
    assert len(rows) == 1
    assert rows[0].count == 2
    assert len(rows[0].derived_from) == 2


async def _seed_product(db_session: AsyncSession, merchant_id: UUID, category: str) -> UUID:
    product_id = uuid4()
    db_session.add(Product(
        id=product_id, merchant_id=merchant_id, business_date=NOW.date(),
        product_code=f"gap-{product_id.hex[:10]}", title="商品", category=category,
        price=Decimal("10.00"), status="ONLINE", listed_at=NOW,
        stock_on_hand=1, stock_reserved=0, content_version=1,
    ))
    await db_session.flush()
    return product_id


@pytest.mark.asyncio
async def test_missing_required_attribute_counts_content_gap(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    product_id = await _seed_product(db_session, merchant_one_id, "女装")
    await derive_content_gap_signal(
        db_session, merchant_id=merchant_one_id, product_id=product_id,
        product_name="商品", content_version=1, now=NOW,
    )
    row = (await db_session.scalars(select(CustomerSignal).where(
        CustomerSignal.merchant_id == merchant_one_id, CustomerSignal.kind == "CONTENT_GAP",
    ))).one()
    assert row.count == 1
    assert row.derived_from == [
        {"source_type": "PRODUCT", "source_id": str(product_id), "content_version": 1}
    ]


@pytest.mark.asyncio
async def test_content_gap_signal_is_idempotent_within_same_content_version(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """同一天、同一次提问重复触发（例如顾客反复刷新）不应无限堆积计数。

    与售后信号「同一来源重试不重复计数」的语义一致，只是 `CONTENT_GAP` 用
    `content_version` 作为去重键——同一版本下的重复提问算同一次事实，
    真正的"又有人问了"只在内容更新后的新版本上才重新计数一次。
    """

    product_id = await _seed_product(db_session, merchant_one_id, "女装")
    for _ in range(3):
        await derive_content_gap_signal(
            db_session, merchant_id=merchant_one_id, product_id=product_id,
            product_name="商品", content_version=1, now=NOW,
        )
    row = (await db_session.scalars(select(CustomerSignal).where(
        CustomerSignal.merchant_id == merchant_one_id, CustomerSignal.kind == "CONTENT_GAP",
    ))).one()
    assert row.count == 1
    assert len(row.derived_from) == 1


@pytest.mark.asyncio
async def test_content_gap_signal_recounts_after_content_version_changes(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """商品内容更新后（`content_version` 递增）缺口若仍未补，下一次提问重新计数一次；
    这与计划步骤 1 的「更新前的那一次，不再增加」区分开——本测试验证的是更新*之后*
    若缺口依旧存在，信号仍需继续反映现状，不是永久停止计数。"""

    product_id = await _seed_product(db_session, merchant_one_id, "女装")
    await derive_content_gap_signal(
        db_session, merchant_id=merchant_one_id, product_id=product_id,
        product_name="商品", content_version=1, now=NOW,
    )
    await derive_content_gap_signal(
        db_session, merchant_id=merchant_one_id, product_id=product_id,
        product_name="商品", content_version=2, now=NOW,
    )
    row = (await db_session.scalars(select(CustomerSignal).where(
        CustomerSignal.merchant_id == merchant_one_id, CustomerSignal.kind == "CONTENT_GAP",
    ))).one()
    assert row.count == 2
    assert row.derived_from == [
        {"source_type": "PRODUCT", "source_id": str(product_id), "content_version": 2}
    ]


@pytest.mark.asyncio
async def test_signal_date_is_business_day_across_utc_midnight(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    after_sale_product = await _seed_product(db_session, merchant_one_id, "测试")
    gap_product = await _seed_product(db_session, merchant_one_id, "女装")
    await derive_after_sale_signals(
        db_session, merchant_id=merchant_one_id,
        kind=AfterSaleType.REFUND_ONLY, sale_id=uuid4(),
        products=[(after_sale_product, "商品")], now=CROSS_DAY,
    )
    await derive_content_gap_signal(
        db_session, merchant_id=merchant_one_id, product_id=gap_product,
        product_name="商品", content_version=1, now=CROSS_DAY,
    )
    rows = list((await db_session.scalars(select(CustomerSignal).where(
        CustomerSignal.merchant_id == merchant_one_id
    ))).all())
    assert sorted(row.kind for row in rows) == ["CONTENT_GAP", "REFUND_REQUESTS"]
    assert {row.signal_date for row in rows} == {date(2026, 9, 25)}
