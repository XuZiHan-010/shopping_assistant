"""ChatBiService 的窗口上卷行为。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.analytics.chatbi_metrics import QaCounters
from app.repositories.chatbi import DailyRow
from app.services.chatbi_service import ChatBiService

MERCHANT_A = uuid4()
MERCHANT_B = uuid4()


def _counters(answer_total: int, adopted: int) -> QaCounters:
    return QaCounters(
        answer_total=answer_total,
        adopted_count=adopted,
        like_count=0,
        dislike_count=0,
        first_pass_count=answer_total,
        business_question_total=answer_total,
        hit_count=answer_total,
        degraded_count=0,
        thinking_sample_count=answer_total,
        thinking_ms_sum=answer_total * 1000,
    )


class FakeChatBiRepository:
    def __init__(self, rows: list[DailyRow]) -> None:
        self._rows = rows

    async def load_daily(self, *, start_date: date, end_date: date) -> list[DailyRow]:
        return [row for row in self._rows if start_date <= row.stat_date <= end_date]


@pytest.mark.asyncio
async def test_overview_rolls_up_across_merchants_and_categories() -> None:
    rows = [
        DailyRow(date(2026, 8, 20), MERCHANT_A, "TRADE", _counters(10, 5)),
        DailyRow(date(2026, 8, 20), MERCHANT_B, "REFUND", _counters(10, 1)),
    ]

    overview = await ChatBiService(FakeChatBiRepository(rows)).overview(
        start_date=date(2026, 8, 20), end_date=date(2026, 8, 20)
    )

    assert overview.counters.answer_total == 20
    assert overview.metrics.adoption_rate == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_overview_daily_points_are_one_per_date() -> None:
    rows = [
        DailyRow(date(2026, 8, 20), MERCHANT_A, "TRADE", _counters(10, 5)),
        DailyRow(date(2026, 8, 20), MERCHANT_B, "REFUND", _counters(10, 1)),
        DailyRow(date(2026, 8, 21), MERCHANT_A, "TRADE", _counters(4, 2)),
    ]

    overview = await ChatBiService(FakeChatBiRepository(rows)).overview(
        start_date=date(2026, 8, 20), end_date=date(2026, 8, 21)
    )

    assert [point.stat_date for point in overview.daily] == [date(2026, 8, 20), date(2026, 8, 21)]
    assert overview.daily[0].answer_total == 20
    assert overview.daily[1].metrics.adoption_rate == pytest.approx(0.50)


@pytest.mark.asyncio
async def test_empty_window_returns_none_metrics_not_zero() -> None:
    overview = await ChatBiService(FakeChatBiRepository([])).overview(
        start_date=date(2026, 8, 20), end_date=date(2026, 8, 21)
    )

    assert overview.counters.answer_total == 0
    assert overview.metrics.adoption_rate is None
    assert overview.daily == []


@pytest.mark.asyncio
async def test_categories_group_by_category_sorted_by_volume() -> None:
    rows = [
        DailyRow(date(2026, 8, 20), MERCHANT_A, "TRADE", _counters(3, 1)),
        DailyRow(date(2026, 8, 20), MERCHANT_B, "REFUND", _counters(9, 3)),
        DailyRow(date(2026, 8, 21), MERCHANT_A, "TRADE", _counters(2, 0)),
        DailyRow(date(2026, 8, 21), MERCHANT_B, "OTHER", _counters(11, 2)),
        DailyRow(date(2026, 8, 21), MERCHANT_A, "ZEBRA", _counters(20, 4)),
    ]

    breakdown = await ChatBiService(FakeChatBiRepository(rows)).categories(
        start_date=date(2026, 8, 20), end_date=date(2026, 8, 21)
    )

    assert [item.category for item in breakdown] == ["ZEBRA", "OTHER", "REFUND", "TRADE"]
    assert breakdown[3].counters.answer_total == 5
