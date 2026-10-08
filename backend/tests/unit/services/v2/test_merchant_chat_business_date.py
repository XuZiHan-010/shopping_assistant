"""商家回合必须告诉模型当前业务日期。

2026-10-07 真实对照发现：系统提示里没有日期，而 `query_metrics` 要求绝对起止日期，
「今天销售额」被按模型自己填的 2025-01-01 查询。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.v2.merchant_chat import business_date_context


def test_today_is_taken_in_the_business_timezone_not_utc() -> None:
    late_utc_evening = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)

    note = business_date_context(late_utc_evening, timezone="Asia/Shanghai")

    assert "2026-10-07" in note
    assert "2026-10-06" not in note
    assert "Asia/Shanghai" in note


def test_weekday_is_stated_so_week_boundaries_need_no_guessing() -> None:
    wednesday = datetime(2026, 10, 7, 4, 0, tzinfo=UTC)

    assert "周三" in business_date_context(wednesday, timezone="Asia/Shanghai")
