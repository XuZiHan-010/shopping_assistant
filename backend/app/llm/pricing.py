"""模型价格版本与单次调用成本（N5 B Task 2；PRD §10.2）。

成本在**写入用量时**按调用当时生效的价格版本算好并存储，查询时不重算；价格变动只追加新版本
（`model_price_versions` 由触发器强制追加写），历史成本因此不会随新价格漂移。

DeepSeek 官方价格分高峰 / 非高峰（2026-10-03 核实
https://api-docs.deepseek.com/quick_start/pricing）：
高峰为 UTC 周一至周五 01:00–04:00 与 06:00–10:00，不含中国法定节假日；其余时段为半价。
节假日表无法在这里确定性维护，**按高峰计**——记账成本只会偏高、不会偏低。
缓存命中单独计价，但缓存不是正确性依赖（Q23）：拿不到命中数时全部按未命中计。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

_PER_TOKEN: Final = Decimal(1_000_000)
_PEAK_HOURS: Final = frozenset({1, 2, 3, 6, 7, 8, 9})


class PricePeriod(StrEnum):
    PEAK = "PEAK"
    OFF_PEAK = "OFF_PEAK"


@dataclass(frozen=True)
class PriceVersion:
    """一条价格版本；单价均为「每百万 token」，币种见 `currency`。"""

    id: UUID
    model: str
    currency: str
    peak_cache_hit: Decimal
    peak_cache_miss: Decimal
    peak_output: Decimal
    off_peak_cache_hit: Decimal
    off_peak_cache_miss: Decimal
    off_peak_output: Decimal
    effective_from: datetime


def price_period(at: datetime) -> PricePeriod:
    if at.tzinfo is None:
        raise ValueError("price_period 需要带时区的时间")
    utc = at.astimezone(UTC)
    if utc.weekday() < 5 and utc.hour in _PEAK_HOURS:
        return PricePeriod.PEAK
    return PricePeriod.OFF_PEAK


def usage_cost(
    version: PriceVersion,
    *,
    at: datetime,
    input_tokens: int,
    cache_hit_tokens: int | None,
    output_tokens: int,
) -> Decimal:
    """`input_tokens` 是全部输入（含缓存命中部分），与 OpenAI 协议的 `prompt_tokens` 同口径。"""

    hits = cache_hit_tokens or 0
    if hits < 0 or hits > input_tokens or input_tokens < 0 or output_tokens < 0:
        raise ValueError("token 计数不合法：缓存命中数必须在 0 与输入总数之间")
    peak = price_period(at) is PricePeriod.PEAK
    hit_price = version.peak_cache_hit if peak else version.off_peak_cache_hit
    miss_price = version.peak_cache_miss if peak else version.off_peak_cache_miss
    output_price = version.peak_output if peak else version.off_peak_output
    return (
        Decimal(hits) * hit_price
        + Decimal(input_tokens - hits) * miss_price
        + Decimal(output_tokens) * output_price
    ) / _PER_TOKEN
