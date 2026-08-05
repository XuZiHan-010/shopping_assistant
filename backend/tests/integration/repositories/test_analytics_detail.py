"""明细查询的行数、截断与列顺序。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract import DETAIL_SPECS
from app.models.analytics import Order, OrderItem, Product, ReturnRecord, SupportTicket
from app.repositories.analytics import AnalyticsRepository

DAY = date(2026, 8, 3)


async def _return_record(session: AsyncSession, merchant_id: UUID, reason: str) -> None:
    """退货明细的最小依赖链：product -> order -> order_item -> return。

    `DETAIL_BY_CATEGORY` 只把 `REFUND` 静态指向 `refunds` 表，`returns` 表
    曾经没有任何路由能到达——`SafeQueryService` 已在 REFUND 类别内部按
    维度/筛选字段与分类关键词做了二次路由（见
    `tests/integration/services/test_safe_query.py` 里的
    `test_refund_category_with_*` 系列），这里仍然直接测 Repository，
    是为了在编排层之下单独钉住「可查询、跨商家不可见」这条不依赖路由逻辑
    的最小行为。
    """

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

    order = Order(
        merchant_id=merchant_id,
        business_date=DAY,
        order_no=f"NO-{uuid4().hex[:8]}",
        buyer_key="buyer",
        order_status="COMPLETED",
        total_amount=Decimal("100.00"),
        paid_amount=Decimal("100.00"),
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
        quantity=1,
        item_amount=Decimal("100.00"),
    )
    session.add(item)
    await session.flush()

    session.add(
        ReturnRecord(
            merchant_id=merchant_id,
            business_date=DAY,
            order_item_id=item.id,
            return_quantity=1,
            return_reason=reason,
            return_status="COMPLETED",
            logistics_status="DELIVERED",
            returned_at=datetime(2026, 8, 4, 3, 0, tzinfo=UTC),
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_returns_detail_is_queryable_and_never_visible_to_other_merchants(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    """§B4 验收「退货明细可查询、跨商家不可见」在 Repository 层的钉子。

    两个商家各留一条退货原因不同的记录：商家一能查到自己那条（且原因字段值
    正确，不是随手返回了任意一行），商家二查不到商家一的记录。
    """

    await _return_record(db_session, merchant_one_id, "尺码不合适")
    await _return_record(db_session, merchant_two_id, "质量问题")
    repository = AnalyticsRepository(db_session)

    owner_result = await repository.detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["returns"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )
    other_result = await repository.detail(
        merchant_id=merchant_two_id,
        spec=DETAIL_SPECS["returns"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert [row["return_reason"] for row in owner_result.rows] == ["尺码不合适"]
    assert [row["return_reason"] for row in other_result.rows] == ["质量问题"]


async def _orders(session: AsyncSession, merchant_id: UUID, count: int) -> None:
    for index in range(count):
        session.add(
            Order(
                merchant_id=merchant_id,
                business_date=DAY,
                order_no=f"NO-{index:05d}-{uuid4().hex[:6]}",
                buyer_key=f"buyer-{index}",
                order_status="COMPLETED",
                total_amount=Decimal("10.00"),
                paid_amount=Decimal("10.00"),
                placed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
                paid_at=datetime(2026, 8, 3, 3, 0, tzinfo=UTC),
            )
        )
    await session.flush()


@pytest.mark.asyncio
async def test_detail_reports_total_rows_beyond_the_preview(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """预览截断但总数照实报，否则用户以为只有 200 单。"""

    await _orders(db_session, merchant_one_id, 205)
    repository = AnalyticsRepository(db_session)

    result = await repository.detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["orders"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert len(result.rows) == 200
    assert result.total_rows == 205
    assert result.truncated is True


@pytest.mark.asyncio
async def test_detail_is_not_marked_truncated_when_it_fits(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _orders(db_session, merchant_one_id, 3)
    repository = AnalyticsRepository(db_session)

    result = await repository.detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["orders"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert result.total_rows == 3
    assert result.truncated is False


@pytest.mark.asyncio
async def test_detail_columns_have_stable_order_and_chinese_labels(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """列顺序不稳定，前端表格每次刷新都会换列；缺中文标签则只能显示英文列名。"""

    await _orders(db_session, merchant_one_id, 1)
    repository = AnalyticsRepository(db_session)

    result = await repository.detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["orders"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert [column.key for column in result.columns] == [
        name for name, _ in DETAIL_SPECS["orders"].columns
    ]
    assert all(column.label for column in result.columns)
    assert set(result.rows[0]) == {column.key for column in result.columns}


@pytest.mark.asyncio
async def test_products_detail_ignores_the_query_window(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """`products.business_date` 是上架日，不是业务事件日。

    演示数据把 24 个商品铺在整整 180 天里，而默认查询窗口只有 7 天：套用
    事件表的时间窗规则，商家问「看看我的商品明细」会拿到 24 个里的约 1 个，
    另外 23 个被静默过滤掉且没有任何提示。这里把两个上架日相隔半年的商品
    放进库里，用一个只覆盖其中一个的窗口去查，两个都必须回来。
    """

    for offset, code in ((0, "SKU-NEW"), (-170, "SKU-OLD")):
        db_session.add(
            Product(
                merchant_id=merchant_one_id,
                business_date=DAY + timedelta(days=offset),
                product_code=code,
                title=f"演示商品 {code}",
                category="女装",
                price=Decimal("100.00"),
                status="ONLINE",
                listed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
            )
        )
    await db_session.flush()

    result = await AnalyticsRepository(db_session).detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["products"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert {row["product_code"] for row in result.rows} == {"SKU-NEW", "SKU-OLD"}
    assert result.total_rows == 2


@pytest.mark.asyncio
async def test_products_detail_still_scopes_to_one_merchant(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    """放宽的只是时间窗；商家隔离是另一条不可放宽的条件。"""

    for merchant_id, code in ((merchant_one_id, "SKU-MINE"), (merchant_two_id, "SKU-THEIRS")):
        db_session.add(
            Product(
                merchant_id=merchant_id,
                business_date=DAY - timedelta(days=170),
                product_code=code,
                title=f"演示商品 {code}",
                category="女装",
                price=Decimal("100.00"),
                status="ONLINE",
                listed_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
            )
        )
    await db_session.flush()

    result = await AnalyticsRepository(db_session).detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["products"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert [row["product_code"] for row in result.rows] == ["SKU-MINE"]


@pytest.mark.asyncio
async def test_support_ticket_detail_reads_every_contract_column(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """工单明细此前没有任何测试真的查过它。

    `detail()` 用 `getattr(table, name)` 解析列名，写错是**请求期**的
    AttributeError；契约层的列名核对（`tests/unit/analytics/test_contract.py`）
    保证名字存在，这条保证这张表真的能被查出来。
    """

    db_session.add(
        SupportTicket(
            merchant_id=merchant_one_id,
            business_date=DAY,
            ticket_no="TK-0001",
            order_id=None,
            ticket_status="OPEN",
            ticket_reason="物流查询",
            opened_at=datetime(2026, 8, 3, 2, 0, tzinfo=UTC),
        )
    )
    await db_session.flush()

    result = await AnalyticsRepository(db_session).detail(
        merchant_id=merchant_one_id,
        spec=DETAIL_SPECS["support_tickets"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert [row["ticket_no"] for row in result.rows] == ["TK-0001"]
    assert set(result.rows[0]) == {name for name, _ in DETAIL_SPECS["support_tickets"].columns}


@pytest.mark.asyncio
async def test_detail_never_returns_other_merchants_rows(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    await _orders(db_session, merchant_one_id, 5)
    repository = AnalyticsRepository(db_session)

    result = await repository.detail(
        merchant_id=merchant_two_id,
        spec=DETAIL_SPECS["orders"],
        filters={},
        start=DAY,
        end=DAY,
        limit=200,
    )

    assert result.rows == []
    assert result.total_rows == 0
