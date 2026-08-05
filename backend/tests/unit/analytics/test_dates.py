"""业务日界与日期范围解析。

时钟必须可注入：跨零点归属是这一层最容易错、也最难靠人工复现的地方。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.analytics.dates import DEFAULT_RANGE_DAYS, business_today, resolve_range
from app.intent.models import DateRange
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
