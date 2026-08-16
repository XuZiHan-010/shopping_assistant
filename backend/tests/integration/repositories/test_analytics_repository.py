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
from app.intent.models import GeneratedMetricPlan
from app.models.analytics import Order, OrderItem, Product, Refund, ReturnRecord
from app.repositories.analytics import AnalyticsRepository
from app.schemas.chat import QuestionCategory

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
    # 走 order_items 路径时，source_tables 得如实报告真正参与聚合的三张表。
    assert result.source_tables == ("order_items", "orders", "products")


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
    assert result.source_tables == ("order_items", "orders", "products")


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
    assert result.source_tables == ("order_items", "orders", "products")


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


async def _fixture_category_order_with_excluded_status(
    session: AsyncSession, merchant_id: UUID
) -> None:
    """同一个类目下两张订单：一张 `COMPLETED`（应计入 GMV），一张 `CANCELLED`

    （不应计入）。两张订单的商品都在「女装」类目下，这样才能验证「同类目内
    也会按订单状态排除」，而不是靠类目不同蒙混过去——如果 GMV 改走
    `order_items.item_amount` 聚合时把 `Order.order_status` 的 FILTER
    弄丢或挂错了列，这张 `CANCELLED` 订单的 500 元会混进「女装」类目的 GMV。
    """

    qualifying_product = Product(
        merchant_id=merchant_id,
        business_date=DAY,
        product_code=f"SKU-{uuid4().hex[:8]}",
        title="演示商品-合格",
        category="女装",
        price=Decimal("100.00"),
        status="ONLINE",
        listed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
    )
    excluded_product = Product(
        merchant_id=merchant_id,
        business_date=DAY,
        product_code=f"SKU-{uuid4().hex[:8]}",
        title="演示商品-被取消",
        category="女装",
        price=Decimal("500.00"),
        status="ONLINE",
        listed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
    )
    session.add_all([qualifying_product, excluded_product])
    await session.flush()

    qualifying_order = Order(
        merchant_id=merchant_id,
        business_date=DAY,
        order_no=f"NO-{uuid4().hex[:10]}",
        buyer_key="buyer-qualifying",
        order_status="COMPLETED",
        total_amount=Decimal("100.00"),
        paid_amount=Decimal("100.00"),
        placed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        paid_at=datetime(2026, 8, 3, 3, 0, tzinfo=UTC),
    )
    excluded_order = Order(
        merchant_id=merchant_id,
        business_date=DAY,
        order_no=f"NO-{uuid4().hex[:10]}",
        buyer_key="buyer-excluded",
        order_status="CANCELLED",
        total_amount=Decimal("500.00"),
        paid_amount=Decimal("500.00"),
        placed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        paid_at=None,
    )
    session.add_all([qualifying_order, excluded_order])
    await session.flush()

    session.add_all(
        [
            OrderItem(
                merchant_id=merchant_id,
                business_date=DAY,
                order_id=qualifying_order.id,
                product_id=qualifying_product.id,
                quantity=1,
                item_amount=Decimal("100.00"),
            ),
            OrderItem(
                merchant_id=merchant_id,
                business_date=DAY,
                order_id=excluded_order.id,
                product_id=excluded_product.id,
                quantity=1,
                item_amount=Decimal("500.00"),
            ),
        ]
    )
    await session.flush()


@pytest.mark.asyncio
async def test_gmv_by_category_still_excludes_disqualifying_order_status(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """`gmv` 改走 order_items.item_amount 聚合之后，订单状态过滤必须依然生效——

    `CANCELLED` 订单的 500 元不能因为改了聚合基础列就漏进「女装」类目的 GMV。
    """

    await _fixture_category_order_with_excluded_status(db_session, merchant_one_id)
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
    assert by_category == {"女装": Decimal("100.00")}


async def _generated_metric_row(
    session: AsyncSession,
    merchant_id: UUID,
    *,
    spu_id: str,
    city: str,
    paid_amount: Decimal,
    refund_amount: Decimal | None = None,
    order_status: str = "COMPLETED",
    refund_status: str = "REFUNDED",
) -> None:
    product = Product(
        merchant_id=merchant_id,
        business_date=DAY,
        product_code=f"SKU-{spu_id}",
        spu_id=spu_id,
        title=f"商品 {spu_id}",
        category="女装",
        price=paid_amount,
        status="ONLINE",
        listed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
    )
    session.add(product)
    await session.flush()
    order = Order(
        merchant_id=merchant_id,
        business_date=DAY,
        order_no=f"NO-{spu_id}-{uuid4().hex[:6]}",
        buyer_key=f"buyer-{spu_id}",
        address_city_name=city,
        order_status=order_status,
        total_amount=paid_amount,
        paid_amount=paid_amount,
        placed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        paid_at=datetime(2026, 8, 3, 3, 0, tzinfo=UTC),
    )
    session.add(order)
    await session.flush()
    item = OrderItem(
        merchant_id=merchant_id,
        business_date=DAY,
        order_id=order.id,
        product_id=product.id,
        quantity=2,
        item_amount=paid_amount,
    )
    session.add(item)
    await session.flush()
    if refund_amount is not None:
        session.add(
            Refund(
                merchant_id=merchant_id,
                business_date=DAY,
                order_item_id=item.id,
                refund_amount=refund_amount,
                refund_reason="尺码不合适",
                refund_status=refund_status,
                refunded_at=datetime(2026, 8, 3, 4, 0, tzinfo=UTC),
            )
        )
        await session.flush()


@pytest.mark.asyncio
async def test_generated_metric_uses_fixed_trade_and_refund_templates_with_merchant_scope(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    await _generated_metric_row(
        db_session,
        merchant_one_id,
        spu_id="SPU-ONE",
        city="杭州市",
        paid_amount=Decimal("120.00"),
        refund_amount=Decimal("30.00"),
    )
    await _generated_metric_row(
        db_session,
        merchant_two_id,
        spu_id="SPU-TWO",
        city="北京市",
        paid_amount=Decimal("999.00"),
        refund_amount=Decimal("99.00"),
    )
    repository = AnalyticsRepository(db_session)

    trade = await repository.generated_metric(
        merchant_id=merchant_one_id,
        category=QuestionCategory.TRADE,
        plan=GeneratedMetricPlan(
            name="按 SPU 看成交表现",
            unit="元",
            group_by="spu_id",
        ),
        start=DAY,
        end=DAY,
        limit=200,
    )
    refund = await repository.generated_metric(
        merchant_id=merchant_one_id,
        category=QuestionCategory.REFUND,
        plan=GeneratedMetricPlan(
            name="按城市看退款表现",
            unit="元",
            group_by="address_city_name",
        ),
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert trade.rows == [
        {
            "spu_id": "SPU-ONE",
            "spu_name": "商品 SPU-ONE",
            "order_count": 1,
            "order_user_count": 1,
            "quantity": 2,
            "paid_amount": Decimal("120.00"),
        }
    ]
    assert refund.rows == [
        {
            "address_city_name": "杭州市",
            "refund_count": 1,
            "refund_user_count": 1,
            "refund_amount": Decimal("30.00"),
        }
    ]
    assert trade.source_tables == ("orders", "order_items", "products")
    assert refund.source_tables == ("refunds", "order_items", "orders")


@pytest.mark.asyncio
async def test_generated_metric_allows_city_filter_without_a_group(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _generated_metric_row(
        db_session,
        merchant_one_id,
        spu_id="SPU-HZ",
        city="杭州市",
        paid_amount=Decimal("100.00"),
    )
    await _generated_metric_row(
        db_session,
        merchant_one_id,
        spu_id="SPU-SZ",
        city="深圳市",
        paid_amount=Decimal("200.00"),
    )

    result = await AnalyticsRepository(db_session).generated_metric(
        merchant_id=merchant_one_id,
        category=QuestionCategory.TRADE,
        plan=GeneratedMetricPlan(
            name="杭州成交表现",
            unit="元",
            filter_column="address_city_name",
            filter_value="杭州市",
        ),
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert result.rows == [
        {
            "order_count": 1,
            "order_user_count": 1,
            "quantity": 2,
            "paid_amount": Decimal("100.00"),
        }
    ]


@pytest.mark.asyncio
async def test_generated_metric_reports_the_exact_total_when_preview_is_truncated(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    for index in range(201):
        await _generated_metric_row(
            db_session,
            merchant_one_id,
            spu_id=f"SPU-{index:03d}",
            city="杭州市",
            paid_amount=Decimal("1.00"),
        )

    result = await AnalyticsRepository(db_session).generated_metric(
        merchant_id=merchant_one_id,
        category=QuestionCategory.TRADE,
        plan=GeneratedMetricPlan(
            name="按 SPU 看成交表现",
            unit="元",
            group_by="spu_id",
        ),
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert len(result.rows) == 200
    assert result.total_rows == 201
    assert result.truncated is True


@pytest.mark.asyncio
async def test_generated_refund_metric_excludes_pending_and_rejected_refunds(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """未真正退款的申请不能被算进临时分组指标的退款金额/笔数。"""

    await _generated_metric_row(
        db_session,
        merchant_one_id,
        spu_id="SPU-DONE",
        city="杭州市",
        paid_amount=Decimal("100.00"),
        refund_amount=Decimal("30.00"),
        refund_status="REFUNDED",
    )
    await _generated_metric_row(
        db_session,
        merchant_one_id,
        spu_id="SPU-PENDING",
        city="杭州市",
        paid_amount=Decimal("100.00"),
        refund_amount=Decimal("50.00"),
        refund_status="PENDING",
    )
    await _generated_metric_row(
        db_session,
        merchant_one_id,
        spu_id="SPU-REJECTED",
        city="杭州市",
        paid_amount=Decimal("100.00"),
        refund_amount=Decimal("70.00"),
        refund_status="REJECTED",
    )

    result = await AnalyticsRepository(db_session).generated_metric(
        merchant_id=merchant_one_id,
        category=QuestionCategory.REFUND,
        plan=GeneratedMetricPlan(
            name="按城市看退款表现",
            unit="元",
            group_by="address_city_name",
        ),
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert result.rows == [
        {
            "address_city_name": "杭州市",
            "refund_count": 1,
            "refund_user_count": 1,
            "refund_amount": Decimal("30.00"),
        }
    ]


@pytest.mark.asyncio
async def test_generated_trade_metric_excludes_unpaid_orders_entirely(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """从未付款的订单不能在临时分组指标里凭空产出一行全零/全空的分组。"""

    await _generated_metric_row(
        db_session,
        merchant_one_id,
        spu_id="SPU-PAID",
        city="杭州市",
        paid_amount=Decimal("100.00"),
        order_status="COMPLETED",
    )
    await _generated_metric_row(
        db_session,
        merchant_one_id,
        spu_id="SPU-CANCELLED",
        city="杭州市",
        paid_amount=Decimal("999.00"),
        order_status="CANCELLED",
    )

    result = await AnalyticsRepository(db_session).generated_metric(
        merchant_id=merchant_one_id,
        category=QuestionCategory.TRADE,
        plan=GeneratedMetricPlan(
            name="按 SPU 看成交表现",
            unit="元",
            group_by="spu_id",
        ),
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert [row["spu_id"] for row in result.rows] == ["SPU-PAID"]
    assert result.total_rows == 1
