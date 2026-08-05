"""受控聚合查询。

用真实 PostgreSQL：这一层的价值全在 SQL 本身（隔离、聚合、分组、比例重算），
用假仓储测等于什么都没测。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract import METRIC_SPECS
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord
from app.repositories.analytics import AnalyticsRepository

DAY = date(2026, 8, 3)
NEXT_DAY = date(2026, 8, 4)


async def _fixture_rows(session: AsyncSession, merchant_id: UUID) -> UUID:
    """两天各一单，第二天那单退货 2 件、退款一笔。返回第一天的订单项 id。"""

    product = Product(
        merchant_id=merchant_id,
        business_date=DAY,
        product_code=f"SKU-{uuid4().hex[:8]}",
        title="演示商品",
        category="女装",
        price=Decimal("100.00"),
        status="ONLINE",
        listed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
    )
    session.add(product)
    await session.flush()

    first_item_id = uuid4()
    for index, (day, quantity) in enumerate(((DAY, 4), (NEXT_DAY, 6))):
        order = Order(
            merchant_id=merchant_id,
            business_date=day,
            order_no=f"NO-{uuid4().hex[:10]}",
            buyer_key=f"buyer-{index}",
            order_status="COMPLETED",
            total_amount=Decimal("100.00") * quantity,
            paid_amount=Decimal("100.00") * quantity,
            placed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
            paid_at=datetime(2026, 8, 3, 3, 0, tzinfo=UTC),
        )
        session.add(order)
        await session.flush()
        item = OrderItem(
            id=first_item_id if index == 0 else uuid4(),
            merchant_id=merchant_id,
            business_date=day,
            order_id=order.id,
            product_id=product.id,
            quantity=quantity,
            item_amount=Decimal("100.00") * quantity,
        )
        session.add(item)
        await session.flush()
        if index == 1:
            session.add(
                ReturnRecord(
                    merchant_id=merchant_id,
                    business_date=NEXT_DAY,
                    order_item_id=item.id,
                    return_quantity=2,
                    return_reason="尺码不合适",
                    return_status="COMPLETED",
                    logistics_status="DELIVERED",
                    returned_at=datetime(2026, 8, 4, 3, 0, tzinfo=UTC),
                )
            )
            session.add(
                Refund(
                    merchant_id=merchant_id,
                    business_date=NEXT_DAY,
                    order_item_id=item.id,
                    refund_amount=Decimal("200.00"),
                    refund_reason="尺码不合适",
                    refund_status="REFUNDED",
                    refunded_at=datetime(2026, 8, 4, 4, 0, tzinfo=UTC),
                )
            )
    await session.flush()
    return first_item_id


@pytest.mark.asyncio
async def test_aggregate_sums_gmv_over_the_range(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert result.rows == [{"gmv": Decimal("1000.00")}]
    assert result.source_tables == ("orders",)


@pytest.mark.asyncio
async def test_aggregate_groups_by_date_in_stable_order(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=("date",),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert [row["date"] for row in result.rows] == [DAY, NEXT_DAY]
    assert [column.key for column in result.columns] == ["date", "gmv"]
    assert [column.label for column in result.columns] == ["日期", "成交 GMV"]


@pytest.mark.asyncio
async def test_other_merchants_rows_are_never_visible(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    """没有这条，B4 就是把 B1 建立的隔离在查询层重新打开。"""

    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_two_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert result.rows == [{"gmv": None}]


@pytest.mark.asyncio
async def test_return_rate_is_recomputed_over_the_interval(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """退货 2 件 ÷ 同期订单项 10 件 = 20%。按日均会算成 (0% + 33.3%)/2 = 16.7%。"""

    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["return_rate"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert result.rows[0]["return_rate"] == pytest.approx(Decimal("0.20"), abs=Decimal("0.001"))


@pytest.mark.asyncio
async def test_return_count_reads_returns_not_refunds(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """「退货量」返回 2 件而不是 200 元——这正是分表要防的混淆。"""

    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    returned = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["return_count"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )
    refunded = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["refund_amount"],
        dimensions=(),
        filters={},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert returned.rows == [{"return_count": 2}]
    assert refunded.rows == [{"refund_amount": Decimal("200.00")}]


@pytest.mark.asyncio
async def test_filter_values_are_bound_not_interpolated(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """注入串必须被当成普通字符串值，命中零行而不是改变语义。"""

    await _fixture_rows(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=(),
        filters={"category": "女装' OR '1'='1"},
        start=DAY,
        end=NEXT_DAY,
        limit=200,
    )

    assert result.rows == [{"gmv": None}]


async def _fixture_cross_category_order(session: AsyncSession, merchant_id: UUID) -> None:
    """一张订单横跨两个类目：女装两个商品、男装一个商品，订单项金额

    分别是 100 / 50 / 150，加总等于整单实付金额 300。

    钉住的是 `orders -> order_items -> products` 这条 join 路径：女装类目下有
    两个订单项都属于同一张订单，如果聚合仍然基于 `orders` 的行（会被 join
    按订单项展开），`count(orders.id)` 会把这一张订单数成两单，
    `sum(orders.paid_amount)` 也会把整单金额重复算给女装和男装各一份。
    """

    products = [
        Product(
            merchant_id=merchant_id,
            business_date=DAY,
            product_code=f"SKU-{uuid4().hex[:8]}",
            title=f"演示商品{index}",
            category=category,
            price=Decimal("100.00"),
            status="ONLINE",
            listed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        )
        for index, category in enumerate(("女装", "女装", "男装"))
    ]
    session.add_all(products)
    await session.flush()

    order = Order(
        merchant_id=merchant_id,
        business_date=DAY,
        order_no=f"NO-{uuid4().hex[:10]}",
        buyer_key="buyer-cross-category",
        order_status="COMPLETED",
        total_amount=Decimal("300.00"),
        paid_amount=Decimal("300.00"),
        placed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        paid_at=datetime(2026, 8, 3, 3, 0, tzinfo=UTC),
    )
    session.add(order)
    await session.flush()

    amounts = (Decimal("100.00"), Decimal("50.00"), Decimal("150.00"))
    for product, amount in zip(products, amounts, strict=True):
        session.add(
            OrderItem(
                merchant_id=merchant_id,
                business_date=DAY,
                order_id=order.id,
                product_id=product.id,
                quantity=1,
                item_amount=amount,
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_gmv_without_dimension_is_not_inflated_by_product_join(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """基线：不带维度/筛选压根不需要 join products，确认修复没有动到这条路径。"""

    await _fixture_cross_category_order(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=(),
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert result.rows == [{"gmv": Decimal("300.00")}]


@pytest.mark.asyncio
async def test_gmv_by_category_sums_back_to_the_order_amount(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """按类目拆分必须用 order_items.item_amount 分摊到各类目，而不是把整单

    金额算给它涉及的每一个类目——否则跨类目订单的 GMV 会被报出成倍数。
    """

    await _fixture_cross_category_order(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["gmv"],
        dimensions=("category",),
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    by_category = {row["category"]: row["gmv"] for row in result.rows}
    assert by_category == {"女装": Decimal("150.00"), "男装": Decimal("150.00")}
    assert sum(by_category.values()) == Decimal("300.00")


@pytest.mark.asyncio
async def test_order_count_by_category_does_not_double_count_the_same_order(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """女装类目下有 2 个订单项，都属于同一张订单——join 展开会让

    `count(orders.id)` 数出 2 单，实际只有 1 单，必须改用 distinct。
    """

    await _fixture_cross_category_order(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["order_count"],
        dimensions=("category",),
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    by_category = {row["category"]: row["order_count"] for row in result.rows}
    assert by_category == {"女装": 1, "男装": 1}


@pytest.mark.asyncio
async def test_successful_order_count_by_category_does_not_double_count(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """`successful_order_count` 同样基于 `count(orders.id)` 加 FILTER，

    受同一条 join 展开影响，需要同样的 distinct 修复。
    """

    await _fixture_cross_category_order(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["successful_order_count"],
        dimensions=("category",),
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    by_category = {row["category"]: row["successful_order_count"] for row in result.rows}
    assert by_category == {"女装": 1, "男装": 1}


@pytest.mark.asyncio
async def test_paying_user_count_by_category_is_not_affected_by_join_fanout(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """`distinct(buyer_key)` 本身就对重复行免疫：这里验证它确实不受影响，

    不需要跟着 order_count 那套 distinct(order id) 的修复走。
    """

    await _fixture_cross_category_order(db_session, merchant_one_id)
    repository = AnalyticsRepository(db_session)

    result = await repository.aggregate(
        merchant_id=merchant_one_id,
        metric=METRIC_SPECS["paying_user_count"],
        dimensions=("category",),
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    by_category = {row["category"]: row["paying_user_count"] for row in result.rows}
    assert by_category == {"女装": 1, "男装": 1}
