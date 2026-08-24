"""业务日界与查询区间解析。

时钟从参数进来，不在这里读——「昨天」跨零点的归属必须能被冻结时钟测试覆盖。
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from app.intent.models import ComparisonMode, DateRange
from app.intent.whitelist import MAX_QUERY_DAYS

#: 模型没给日期时的默认窗口。演示数据覆盖 180 天，7 天是最常见的经营问法。
DEFAULT_RANGE_DAYS: Final[int] = 7


class FutureRangeError(ValueError):
    """请求区间整体位于未来，没有可查询的经营数据。

    调用方（Task 7 的 `SafeQueryService`）应捕获后转成
    `UnsupportedQueryError`，而不是把这里的 `reason` 当成普通的调整说明——
    这条路径没有合法区间可返回，不能像 `notes` 一样被静默吞掉。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        #: 可直接展示给商家的中文拒绝原因。
        self.reason = reason


def business_today(now: datetime, *, timezone: str) -> date:
    """把注入的时钟换算到业务时区后取日期，作为全系统唯一的「今天」判定点。"""

    return now.astimezone(ZoneInfo(timezone)).date()


def resolve_range(
    requested: DateRange | None,
    *,
    now: datetime,
    timezone: str,
) -> tuple[DateRange, tuple[str, ...]]:
    """产出一定合法的查询区间，并说明做过哪些调整。

    请求区间的起始日期本身就晚于今天时拒绝而不是截断：把结束日截到今天、
    起始日再收敛到同一天，会静默地用「今天」的数据回答一个问未来的问题，
    调用方很容易把这当成对未来区间的正常回答。这里与 B3
    `app.intent.whitelist.validate_intent` 对同型输入的处理保持一致——
    两处都判「起始日期在未来」为不可执行，不是可调整的越界。
    """

    today = business_today(now, timezone=timezone)
    notes: list[str] = []

    if requested is None:
        start = today - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        notes.append(f"问题未指定时间范围，默认查询最近 {DEFAULT_RANGE_DAYS} 天")
        return DateRange(start=start, end=today), tuple(notes)

    if requested.start > today:
        raise FutureRangeError("日期范围完全位于未来，没有可查询的经营数据")

    start, end = requested.start, requested.end
    if end > today:
        end = today
        notes.append("结束日期在未来，已截断到今天")
    if start > end:
        start = end
        notes.append("起始日期晚于结束日期，已收敛为单日")
    if (end - start).days + 1 > MAX_QUERY_DAYS:
        start = end - timedelta(days=MAX_QUERY_DAYS - 1)
        notes.append(f"查询范围超过 {MAX_QUERY_DAYS} 天，已截断为最近 {MAX_QUERY_DAYS} 天")

    return DateRange(start=start, end=end), tuple(notes)


def _add_months(value: date, months: int) -> date:
    """按自然月整体平移一个日期，天数超界时收敛到目标月的最后一天。

    收敛而不是溢出到下个月，是 D3 裁定"未结束的自然月与上月同期比较"的地基：
    8/31 的上一期若溢出成 7/31 之后一天（8/1），基准期就悄悄多算了一天。
    """

    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _add_years(value: date, years: int) -> date:
    """按年平移，2/29 在目标年不是闰年时收敛到 2/28（不溢出到 3/1）。"""

    year = value.year + years
    if value.month == 2 and value.day == 29 and not calendar.isleap(year):
        return date(year, 2, 28)
    return date(year, value.month, value.day)


def shift_baseline_period(current: DateRange, *, mode: ComparisonMode) -> DateRange:
    """把主周期整体平移到对比基准期，供环比/同比一次取两期数据。

    起止两端各自独立平移（而不是先平移 start 再按原时长推 end）：当 start 与 end
    跨越不同长度的月份时（例如 1/31–3/1），只平移 start 会让区间长度失真。
    """

    shift: Callable[[date, int], date]
    if mode is ComparisonMode.PREVIOUS_PERIOD:
        shift = _add_months
    elif mode is ComparisonMode.YEAR_OVER_YEAR:
        shift = _add_years
    else:
        raise ValueError(
            f"comparison mode 必须是 PREVIOUS_PERIOD 或 YEAR_OVER_YEAR，"
            f"收到 {mode!r}（NONE 不应平移）"
        )

    return DateRange(start=shift(current.start, -1), end=shift(current.end, -1))
