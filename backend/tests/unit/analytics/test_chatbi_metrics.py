"""Chat BI 北极星指标的计算口径。"""

from __future__ import annotations

import pytest

from app.analytics.chatbi_metrics import QaCounters, compute_north_star


def _counters(**overrides: int) -> QaCounters:
    values = {
        "answer_total": 100,
        "adopted_count": 40,
        "like_count": 30,
        "dislike_count": 10,
        "first_pass_count": 80,
        "business_question_total": 90,
        "hit_count": 72,
        "degraded_count": 5,
        "thinking_sample_count": 100,
        "thinking_ms_sum": 250_000,
    }
    values.update(overrides)
    return QaCounters(**values)


def test_computes_north_star_metrics_from_additive_counters() -> None:
    """将任一分子、分母或平均时长口径改错时，本测试应失败。"""
    metrics = compute_north_star(_counters())
    assert metrics.adoption_rate == pytest.approx(0.40)
    assert metrics.user_accuracy_rate == pytest.approx(0.75)
    assert metrics.system_accuracy_rate == pytest.approx(0.80)
    assert metrics.hit_rate == pytest.approx(0.80)
    assert metrics.failure_rate == pytest.approx(0.05)
    assert metrics.avg_thinking_ms == pytest.approx(2500.0)


def test_returns_none_when_metric_has_no_denominator() -> None:
    """将零样本显示为零比率时，本测试应失败。"""
    metrics = compute_north_star(QaCounters.zero())
    assert all(value is None for value in vars(metrics).values())


def test_user_accuracy_uses_only_reactions_and_merge_precedes_division() -> None:
    """用全部回答作分母或平均日比率时，本测试应失败。"""
    assert compute_north_star(_counters(like_count=0, dislike_count=0)).user_accuracy_rate is None
    merged = _counters().merge(_counters(adopted_count=0))
    assert compute_north_star(merged).adoption_rate == pytest.approx(0.20)


def test_thinking_average_ignores_answers_without_elapsed_ms() -> None:
    """把缺失耗时当作零时，本测试应失败。"""
    assert compute_north_star(_counters(thinking_sample_count=50)).avg_thinking_ms == pytest.approx(
        5000.0
    )
