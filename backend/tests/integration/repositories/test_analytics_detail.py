"""明细查询的行数、截断与列顺序。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.contract import DETAIL_SPECS
from app.models.analytics import Order
from app.repositories.analytics import AnalyticsRepository

DAY = date(2026, 8, 3)


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
