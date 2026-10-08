"""OperationalMetrics：进程内运维计数器。"""

from __future__ import annotations

import pytest

from app.core.metrics import OperationalMetrics


def test_rate_limit_hits_and_degraded_count_are_plain_counters() -> None:
    metrics = OperationalMetrics()

    metrics.rate_limit_hits += 1
    metrics.rate_limit_hits += 1
    metrics.degraded_count += 1

    assert metrics.rate_limit_hits == 2
    assert metrics.degraded_count == 1


def test_record_error_code_accumulates_per_code() -> None:
    metrics = OperationalMetrics()

    metrics.record_error_code("RATE_LIMITED")
    metrics.record_error_code("RATE_LIMITED")
    metrics.record_error_code("AUTH_REQUIRED")

    assert metrics.error_code_counts == {"RATE_LIMITED": 2, "AUTH_REQUIRED": 1}


def test_error_code_counts_returns_snapshot_not_live_reference() -> None:
    metrics = OperationalMetrics()
    metrics.record_error_code("RATE_LIMITED")

    snapshot = metrics.error_code_counts
    snapshot["RATE_LIMITED"] = 999

    assert metrics.error_code_counts == {"RATE_LIMITED": 1}


def test_route_average_ms_computes_mean_of_recorded_durations() -> None:
    metrics = OperationalMetrics()

    metrics.record_route_duration("/api/chat", 0.100)
    metrics.record_route_duration("/api/chat", 0.300)
    metrics.record_route_duration("/api/health", 0.010)

    averages = metrics.route_average_ms

    assert averages["/api/chat"] == pytest.approx(200.0)
    assert averages["/api/health"] == pytest.approx(10.0)


def test_agent_node_average_ms_computes_mean_per_node() -> None:
    metrics = OperationalMetrics()

    metrics.record_node_duration("load_context", 0.010)
    metrics.record_node_duration("load_context", 0.030)

    assert metrics.agent_node_average_ms == {"load_context": pytest.approx(20.0)}


def test_route_average_ms_empty_when_nothing_recorded() -> None:
    metrics = OperationalMetrics()

    assert metrics.route_average_ms == {}
    assert metrics.agent_node_average_ms == {}


# ---------- N5 B Task 3：p95 与工具错误率 ----------


def test_route_p95_uses_recent_samples() -> None:
    from app.core.metrics import OperationalMetrics

    metrics = OperationalMetrics()
    for ms in range(1, 101):  # 1..100 ms
        metrics.record_route_duration("/api/x", ms / 1000)

    assert metrics.route_p95_ms["/api/x"] == pytest.approx(95.0, abs=1.0)


def test_route_p95_window_is_bounded() -> None:
    from app.core.metrics import ROUTE_SAMPLE_WINDOW, OperationalMetrics

    metrics = OperationalMetrics()
    for _ in range(ROUTE_SAMPLE_WINDOW):
        metrics.record_route_duration("/api/x", 10.0)  # 旧的慢请求
    for _ in range(ROUTE_SAMPLE_WINDOW):
        metrics.record_route_duration("/api/x", 0.001)

    assert metrics.route_p95_ms["/api/x"] == pytest.approx(1.0)


def test_tool_counters() -> None:
    from app.core.metrics import OperationalMetrics

    metrics = OperationalMetrics()
    metrics.record_tool_call(ok=True)
    metrics.record_tool_call(ok=False)
    metrics.record_tool_call(ok=False)

    assert (metrics.tool_calls_total, metrics.tool_errors_total) == (3, 2)


def test_turn_degradation_counts_whole_turns_by_reason_and_single_sources_separately() -> None:
    """整轮降级按原因码计数；回答没整轮降级、只是某个来源降级的，另算一类（PRD §10.4）。"""

    metrics = OperationalMetrics()

    metrics.record_turn(degraded=True, reason="BUDGET", degraded_sources=[])
    metrics.record_turn(degraded=True, reason="BUDGET", degraded_sources=["KNOWLEDGE"])
    metrics.record_turn(degraded=True, reason=None, degraded_sources=[])
    metrics.record_turn(degraded=False, reason=None, degraded_sources=["KNOWLEDGE"])
    metrics.record_turn(degraded=False, reason=None, degraded_sources=[])

    assert metrics.degraded_count == 3
    assert metrics.degraded_reason_counts == {"BUDGET": 2, "UNKNOWN": 1}
    assert sum(metrics.degraded_reason_counts.values()) == metrics.degraded_count
    # 整轮已降级的回合不再重复计入「单来源降级」。
    assert metrics.source_degraded_counts == {"KNOWLEDGE": 1}


def test_degradation_counts_return_snapshots_not_live_references() -> None:
    metrics = OperationalMetrics()
    metrics.record_turn(degraded=True, reason="LIMIT", degraded_sources=[])

    metrics.degraded_reason_counts["LIMIT"] = 999
    metrics.source_degraded_counts["KNOWLEDGE"] = 999

    assert metrics.degraded_reason_counts == {"LIMIT": 1}
    assert metrics.source_degraded_counts == {}
