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
