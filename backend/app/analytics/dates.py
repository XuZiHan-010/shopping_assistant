"""业务日界与查询区间解析。

时钟从参数进来，不在这里读——「昨天」跨零点的归属必须能被冻结时钟测试覆盖。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from app.intent.models import DateRange
from app.intent.whitelist import MAX_QUERY_DAYS

#: 模型没给日期时的默认窗口。演示数据覆盖 180 天，7 天是最常见的经营问法。
DEFAULT_RANGE_DAYS: Final[int] = 7


def business_today(now: datetime, *, timezone: str) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


def resolve_range(
    requested: DateRange | None,
    *,
    now: datetime,
    timezone: str,
) -> tuple[DateRange, tuple[str, ...]]:
    """产出一定合法的查询区间，并说明做过哪些调整。"""

    today = business_today(now, timezone=timezone)
    notes: list[str] = []

    if requested is None:
        start = today - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        notes.append(f"问题未指定时间范围，默认查询最近 {DEFAULT_RANGE_DAYS} 天")
        return DateRange(start=start, end=today), tuple(notes)

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
