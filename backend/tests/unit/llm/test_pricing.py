"""成本按调用当时的价格版本计算（N5 B Task 2；PRD §10.2）。

DeepSeek 官方价格分高峰 / 非高峰（2026-10-03 核实，
https://api-docs.deepseek.com/quick_start/pricing）：
高峰为 UTC 周一至周五 01:00–04:00 与 06:00–10:00（不含中国法定节假日），其余时段半价。
节假日无法在这里确定性判断，按高峰计——记账成本只会偏高、不会偏低。
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.llm.pricing import PricePeriod, PriceVersion, price_period, usage_cost

FLASH = PriceVersion(
    id=UUID(int=1),
    model="deepseek-flash",
    currency="USD",
    peak_cache_hit=Decimal("0.006"),
    peak_cache_miss=Decimal("0.3"),
    peak_output=Decimal("1.2"),
    off_peak_cache_hit=Decimal("0.003"),
    off_peak_cache_miss=Decimal("0.15"),
    off_peak_output=Decimal("0.6"),
    effective_from=datetime(2026, 10, 3, tzinfo=UTC),
)


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (datetime(2026, 10, 5, 1, 0, tzinfo=UTC), PricePeriod.PEAK),  # 周一 01:00 起
        (datetime(2026, 10, 5, 3, 59, tzinfo=UTC), PricePeriod.PEAK),
        (datetime(2026, 10, 5, 4, 0, tzinfo=UTC), PricePeriod.OFF_PEAK),  # 04:00 结束
        (datetime(2026, 10, 5, 6, 0, tzinfo=UTC), PricePeriod.PEAK),
        (datetime(2026, 10, 5, 9, 59, tzinfo=UTC), PricePeriod.PEAK),
        (datetime(2026, 10, 5, 10, 0, tzinfo=UTC), PricePeriod.OFF_PEAK),
        (datetime(2026, 10, 5, 0, 59, tzinfo=UTC), PricePeriod.OFF_PEAK),
        (datetime(2026, 10, 9, 7, 0, tzinfo=UTC), PricePeriod.PEAK),  # 周五
        (datetime(2026, 10, 10, 7, 0, tzinfo=UTC), PricePeriod.OFF_PEAK),  # 周六
        (datetime(2026, 10, 11, 2, 0, tzinfo=UTC), PricePeriod.OFF_PEAK),  # 周日
    ],
)
def test_price_period_follows_official_utc_windows(at: datetime, expected: PricePeriod) -> None:
    assert price_period(at) is expected


def test_price_period_uses_utc_even_for_other_timezones() -> None:
    from zoneinfo import ZoneInfo

    # 北京时间周一 09:30 = UTC 周一 01:30（高峰）
    assert price_period(datetime(2026, 10, 5, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))) is (
        PricePeriod.PEAK
    )


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        price_period(datetime(2026, 10, 5, 2, 0))


def test_cost_splits_cache_hit_and_miss_and_uses_period_prices() -> None:
    peak = usage_cost(
        FLASH,
        at=datetime(2026, 10, 5, 2, 0, tzinfo=UTC),
        input_tokens=1_000_000,
        cache_hit_tokens=400_000,
        output_tokens=500_000,
    )
    # 命中 0.4M × 0.006 + 未命中 0.6M × 0.3 + 输出 0.5M × 1.2
    assert peak == Decimal("0.0024") + Decimal("0.18") + Decimal("0.6")

    off_peak = usage_cost(
        FLASH,
        at=datetime(2026, 10, 10, 2, 0, tzinfo=UTC),
        input_tokens=1_000_000,
        cache_hit_tokens=400_000,
        output_tokens=500_000,
    )
    assert off_peak * 2 == peak


def test_unknown_cache_split_bills_all_input_as_cache_miss() -> None:
    """缓存不作为正确性依赖（Q23）：拿不到命中数时按全部未命中计，只会偏高。"""

    cost = usage_cost(
        FLASH,
        at=datetime(2026, 10, 10, 2, 0, tzinfo=UTC),
        input_tokens=1_000_000,
        cache_hit_tokens=None,
        output_tokens=0,
    )
    assert cost == Decimal("0.15")


def test_cache_hits_cannot_exceed_input() -> None:
    with pytest.raises(ValueError):
        usage_cost(
            FLASH,
            at=datetime(2026, 10, 10, 2, 0, tzinfo=UTC),
            input_tokens=10,
            cache_hit_tokens=11,
            output_tokens=0,
        )
