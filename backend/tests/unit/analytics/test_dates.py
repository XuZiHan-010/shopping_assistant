"""业务日界与日期范围解析。

时钟必须可注入：跨零点归属是这一层最容易错、也最难靠人工复现的地方。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.analytics.dates import (
    DEFAULT_RANGE_DAYS,
    FutureRangeError,
    business_today,
    resolve_range,
    shift_baseline_period,
)
from app.intent.models import ComparisonMode, DateRange
from app.intent.whitelist import MAX_QUERY_DAYS

TZ = "Asia/Shanghai"


def test_utc_evening_still_belongs_to_the_same_business_day() -> None:
    """UTC 15:30 是北京时间 23:30，仍算当天。"""

    assert business_today(datetime(2026, 8, 4, 15, 30, tzinfo=UTC), timezone=TZ) == date(2026, 8, 4)


def test_utc_after_16_rolls_over_to_the_next_business_day() -> None:
    """UTC 16:30 已是北京时间次日 00:30。按 UTC 判定会把「昨天」整体错位一天。"""

    assert business_today(datetime(2026, 8, 4, 16, 30, tzinfo=UTC), timezone=TZ) == date(2026, 8, 5)


def test_missing_range_defaults_to_the_recent_window() -> None:
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)

    resolved, notes = resolve_range(None, now=now, timezone=TZ)

    assert resolved.end == date(2026, 8, 4)
    assert (resolved.end - resolved.start).days + 1 == DEFAULT_RANGE_DAYS
    assert any("默认" in note for note in notes)


def test_requested_range_is_preserved_when_legal() -> None:
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    requested = DateRange(start=date(2026, 7, 1), end=date(2026, 7, 31))

    resolved, notes = resolve_range(requested, now=now, timezone=TZ)

    assert resolved == requested
    assert notes == ()


def test_future_end_is_clamped_to_the_business_today() -> None:
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    requested = DateRange(start=date(2026, 8, 1), end=date(2026, 12, 31))

    resolved, notes = resolve_range(requested, now=now, timezone=TZ)

    assert resolved.end == date(2026, 8, 4)
    assert any("未来" in note for note in notes)


def test_range_longer_than_the_maximum_is_clamped() -> None:
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    requested = DateRange(start=date(2024, 1, 1), end=date(2026, 8, 4))

    resolved, notes = resolve_range(requested, now=now, timezone=TZ)

    assert (resolved.end - resolved.start).days + 1 == MAX_QUERY_DAYS
    assert any(str(MAX_QUERY_DAYS) in note for note in notes)


def test_range_entirely_in_the_future_is_rejected_not_silently_clamped() -> None:
    """起始日期本身就在未来时，不能截断成「今天」的数据静默作答。

    与 `app.intent.whitelist.validate_intent` 对同型输入的处理看齐：
    这种请求没有可查询的经营数据，必须让调用方知道查询没有执行，而不是
    悄悄返回一个「看起来正常」的单日区间。
    """

    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    requested = DateRange(start=date(2026, 9, 1), end=date(2026, 12, 31))

    with pytest.raises(FutureRangeError) as excinfo:
        resolve_range(requested, now=now, timezone=TZ)

    assert "未来" in excinfo.value.reason


def test_reversed_range_not_in_the_future_collapses_to_a_single_day() -> None:
    """起止颠倒但起始日不在未来时，仍按既有语义收敛为单日，而不是拒绝。"""

    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    requested = DateRange(start=date(2026, 8, 3), end=date(2026, 8, 1))

    resolved, notes = resolve_range(requested, now=now, timezone=TZ)

    assert resolved.start == resolved.end == date(2026, 8, 1)
    assert any("起止" in note or "颠倒" in note or "收敛" in note for note in notes)


def test_previous_period_shifts_an_unfinished_month_to_the_same_day_range_last_month() -> None:
    """「本月至今」（8/1–8/22）必须比上月同期（7/1–7/22），不能比完整上月。

    D3 裁定明确要求避免这个错误：完整上月总量天然更大，会把「持平」误判成「下降」。
    """

    current = DateRange(start=date(2026, 8, 1), end=date(2026, 8, 22))

    baseline = shift_baseline_period(current, mode=ComparisonMode.PREVIOUS_PERIOD)

    assert baseline == DateRange(start=date(2026, 7, 1), end=date(2026, 7, 22))


def test_previous_period_clamps_the_day_when_the_prior_month_is_shorter() -> None:
    """3/31 上一个月没有 31 号，必须收敛到 2 月的最后一天，而不是溢出到 3 月。"""

    current = DateRange(start=date(2026, 3, 31), end=date(2026, 3, 31))

    baseline = shift_baseline_period(current, mode=ComparisonMode.PREVIOUS_PERIOD)

    assert baseline == DateRange(start=date(2026, 2, 28), end=date(2026, 2, 28))


def test_previous_period_crosses_the_year_boundary() -> None:
    """1 月的上一期是去年 12 月，年份必须跟着回退。"""

    current = DateRange(start=date(2026, 1, 1), end=date(2026, 1, 10))

    baseline = shift_baseline_period(current, mode=ComparisonMode.PREVIOUS_PERIOD)

    assert baseline == DateRange(start=date(2025, 12, 1), end=date(2025, 12, 10))


def test_year_over_year_shifts_back_exactly_one_year() -> None:
    current = DateRange(start=date(2026, 8, 1), end=date(2026, 8, 22))

    baseline = shift_baseline_period(current, mode=ComparisonMode.YEAR_OVER_YEAR)

    assert baseline == DateRange(start=date(2025, 8, 1), end=date(2025, 8, 22))


def test_year_over_year_clamps_leap_day_to_february_28() -> None:
    """2024 是闰年有 2/29，2023 不是闰年，必须收敛到 2/28 而不是报错或溢出到 3/1。"""

    current = DateRange(start=date(2024, 2, 29), end=date(2024, 2, 29))

    baseline = shift_baseline_period(current, mode=ComparisonMode.YEAR_OVER_YEAR)

    assert baseline == DateRange(start=date(2023, 2, 28), end=date(2023, 2, 28))


def test_shift_baseline_period_rejects_none_mode() -> None:
    """NONE 表示不对比，调用方必须先判断过滤，不应该走到这里还要求平移。"""

    current = DateRange(start=date(2026, 8, 1), end=date(2026, 8, 22))

    with pytest.raises(ValueError, match="NONE"):
        shift_baseline_period(current, mode=ComparisonMode.NONE)
