"""Chat BI 北极星指标：从可加计数推导不可加比率。"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class QaCounters:
    answer_total: int
    adopted_count: int
    like_count: int
    dislike_count: int
    first_pass_count: int
    business_question_total: int
    hit_count: int
    degraded_count: int
    thinking_sample_count: int
    thinking_ms_sum: int

    @classmethod
    def zero(cls) -> QaCounters:
        return cls(**{field.name: 0 for field in fields(cls)})

    def merge(self, other: QaCounters) -> QaCounters:
        return replace(
            self,
            **{
                field.name: getattr(self, field.name) + getattr(other, field.name)
                for field in fields(self)
            },
        )


@dataclass(frozen=True)
class NorthStarMetrics:
    adoption_rate: float | None
    user_accuracy_rate: float | None
    system_accuracy_rate: float | None
    avg_thinking_ms: float | None
    hit_rate: float | None
    failure_rate: float | None


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else numerator / denominator


def compute_north_star(counters: QaCounters) -> NorthStarMetrics:
    return NorthStarMetrics(
        adoption_rate=_ratio(counters.adopted_count, counters.answer_total),
        user_accuracy_rate=_ratio(
            counters.like_count, counters.like_count + counters.dislike_count
        ),
        system_accuracy_rate=_ratio(counters.first_pass_count, counters.answer_total),
        avg_thinking_ms=_ratio(counters.thinking_ms_sum, counters.thinking_sample_count),
        hit_rate=_ratio(counters.hit_count, counters.business_question_total),
        failure_rate=_ratio(counters.degraded_count, counters.answer_total),
    )
