"""环比/同比对比查询（D3 裁定：⚪ 我方增强，参考项目没有该能力）。

两期数据必须由后端一次查询取得、变化率必须由后端用 Decimal 计算——模型只表达
「要不要对比、对比哪种周期」，不得自行推算第二期数字或百分比（R4）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import MerchantContext
from app.intent.models import ComparisonMode, DateRange, QueryIntent
from app.models.analytics import Order
from app.repositories.analytics import AnalyticsRepository
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services.safe_query import SafeQueryService, UnsupportedQueryError

NOW = datetime(2026, 8, 22, 2, 0, tzinfo=UTC)


def _service(session: AsyncSession) -> SafeQueryService:
    return SafeQueryService(AnalyticsRepository(session), business_timezone="Asia/Shanghai")


def _intent(**overrides: object) -> QueryIntent:
    base: dict[str, object] = {
        "answer_mode": AnswerMode.METRIC,
        "category": QuestionCategory.TRADE,
        "metric": "gmv",
        "dimensions": [],
        "filters": {},
        "date_range": DateRange(start=date(2026, 8, 1), end=date(2026, 8, 22)),
    }
    base.update(overrides)
    return QueryIntent.model_validate(base)


async def _paid_order(
    session: AsyncSession, merchant_id: UUID, *, business_date: date, amount: str
) -> None:
    session.add(
        Order(
            merchant_id=merchant_id,
            business_date=business_date,
            order_no=f"NO-{uuid4().hex[:8]}",
            buyer_key="buyer-1",
            order_status="COMPLETED",
            total_amount=Decimal(amount),
            paid_amount=Decimal(amount),
            placed_at=NOW,
            paid_at=NOW,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_previous_period_comparison_fetches_both_periods_and_computes_change_ratio(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """8/1–8/22 对比 7/1–7/22（不是完整 7 月），变化率由后端算出。"""

    await _paid_order(db_session, merchant_one_id, business_date=date(2026, 8, 10), amount="150.00")
    await _paid_order(db_session, merchant_one_id, business_date=date(2026, 7, 10), amount="100.00")
    # 完整 7 月里但不在「7/1-7/22 同期」窗口内的订单：若基期算错成整月，会被计入。
    await _paid_order(db_session, merchant_one_id, business_date=date(2026, 7, 25), amount="900.00")

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(comparison=ComparisonMode.PREVIOUS_PERIOD),
        now=NOW,
    )

    assert result.comparison is not None
    assert result.comparison.mode == ComparisonMode.PREVIOUS_PERIOD
    assert result.comparison.baseline_range == DateRange(
        start=date(2026, 7, 1), end=date(2026, 7, 22)
    )
    assert result.comparison.current_value == Decimal("150.00")
    assert result.comparison.baseline_value == Decimal("100.00")
    assert result.comparison.change_ratio == Decimal("50.0")


@pytest.mark.asyncio
async def test_year_over_year_comparison_shifts_back_one_year(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _paid_order(db_session, merchant_one_id, business_date=date(2026, 8, 10), amount="200.00")
    await _paid_order(db_session, merchant_one_id, business_date=date(2025, 8, 10), amount="100.00")

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(comparison=ComparisonMode.YEAR_OVER_YEAR),
        now=NOW,
    )

    assert result.comparison is not None
    assert result.comparison.baseline_range == DateRange(
        start=date(2025, 8, 1), end=date(2025, 8, 22)
    )
    assert result.comparison.change_ratio == Decimal("100.0")


@pytest.mark.asyncio
async def test_zero_baseline_reports_no_ratio_with_an_explicit_note(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """基期无数据时不能算出一个误导性的百分比，必须显式说明算不出来（R7）。"""

    await _paid_order(db_session, merchant_one_id, business_date=date(2026, 8, 10), amount="150.00")
    # 7 月完全没有订单。

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(comparison=ComparisonMode.PREVIOUS_PERIOD),
        now=NOW,
    )

    assert result.comparison is not None
    assert result.comparison.current_value == Decimal("150.00")
    assert result.comparison.baseline_value is None
    assert result.comparison.change_ratio is None
    assert any("对比基期" in note for note in result.notes)


@pytest.mark.asyncio
async def test_comparison_is_rejected_when_dimensions_are_requested(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """对比只支持单一聚合值，按维度拆分会让两期各自变成多行，无法一一对应。"""

    with pytest.raises(UnsupportedQueryError, match="维度"):
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(comparison=ComparisonMode.PREVIOUS_PERIOD, dimensions=["category"]),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_comparison_does_not_leak_another_merchants_baseline_data(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    await _paid_order(db_session, merchant_one_id, business_date=date(2026, 8, 10), amount="150.00")
    await _paid_order(db_session, merchant_one_id, business_date=date(2026, 7, 10), amount="100.00")
    # 商家二的基期数据不得被商家一的对比查询算进去。
    await _paid_order(db_session, merchant_two_id, business_date=date(2026, 7, 10), amount="900.00")

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(comparison=ComparisonMode.PREVIOUS_PERIOD),
        now=NOW,
    )

    assert result.comparison is not None
    assert result.comparison.baseline_value == Decimal("100.00")


@pytest.mark.asyncio
async def test_no_comparison_requested_leaves_the_field_none(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """默认 NONE 不应该触发第二次查询，回归锁死既有行为不变。"""

    await _paid_order(db_session, merchant_one_id, business_date=date(2026, 8, 10), amount="150.00")

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id), _intent(), now=NOW
    )

    assert result.comparison is None
