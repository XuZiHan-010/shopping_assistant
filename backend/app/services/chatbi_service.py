"""Chat BI 汇总读取与应用层指标计算。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.analytics.chatbi_metrics import NorthStarMetrics, QaCounters, compute_north_star
from app.repositories.chatbi import DailyRow


class ChatBiRepositoryLike(Protocol):
    async def load_daily(self, *, start_date: date, end_date: date) -> list[DailyRow]: ...


@dataclass(frozen=True)
class DailyPoint:
    stat_date: date
    answer_total: int
    metrics: NorthStarMetrics


@dataclass(frozen=True)
class ChatBiOverview:
    start_date: date
    end_date: date
    counters: QaCounters
    metrics: NorthStarMetrics
    daily: list[DailyPoint]


@dataclass(frozen=True)
class CategoryBreakdown:
    category: str
    counters: QaCounters
    metrics: NorthStarMetrics


class ChatBiService:
    def __init__(self, repository: ChatBiRepositoryLike) -> None:
        self._repository = repository

    async def overview(self, *, start_date: date, end_date: date) -> ChatBiOverview:
        rows = await self._repository.load_daily(start_date=start_date, end_date=end_date)
        by_day: dict[date, QaCounters] = defaultdict(QaCounters.zero)
        total = QaCounters.zero()
        for row in rows:
            by_day[row.stat_date] = by_day[row.stat_date].merge(row.counters)
            total = total.merge(row.counters)
        return ChatBiOverview(
            start_date,
            end_date,
            total,
            compute_north_star(total),
            [
                DailyPoint(day, counters.answer_total, compute_north_star(counters))
                for day, counters in sorted(by_day.items())
            ],
        )

    async def categories(self, *, start_date: date, end_date: date) -> list[CategoryBreakdown]:
        rows = await self._repository.load_daily(start_date=start_date, end_date=end_date)
        grouped: dict[str, QaCounters] = defaultdict(QaCounters.zero)
        for row in rows:
            grouped[row.category] = grouped[row.category].merge(row.counters)
        breakdown = [
            CategoryBreakdown(category, counters, compute_north_star(counters))
            for category, counters in grouped.items()
        ]
        return sorted(breakdown, key=lambda item: (-item.counters.answer_total, item.category))
