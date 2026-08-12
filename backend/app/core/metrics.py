"""进程内运维指标：限流命中、降级次数、错误码分布、路由与 Agent 节点耗时。

和 ``app.core.rate_limit.SlidingWindowRateLimiter`` 共享同一份约束：不落库、
进程重启归零，多实例部署下互不同步，只是近似值——见 ``docs/deployment.md``。
``GET /api/admin/ops/status``（B7 运维端点）是这份数据唯一的消费方。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _RunningAverage:
    count: int = 0
    total_seconds: float = 0.0

    def record(self, duration_seconds: float) -> None:
        self.count += 1
        self.total_seconds += duration_seconds

    @property
    def average_ms(self) -> float:
        if self.count == 0:
            return 0.0
        return (self.total_seconds / self.count) * 1000


class OperationalMetrics:
    """``app.state.metrics`` 挂载的唯一运维计数器实例。"""

    def __init__(self) -> None:
        self.rate_limit_hits = 0
        self.degraded_count = 0
        self._error_code_counts: dict[str, int] = {}
        self._route_durations: dict[str, _RunningAverage] = {}
        self._agent_node_durations: dict[str, _RunningAverage] = {}

    def record_error_code(self, code: str) -> None:
        self._error_code_counts[code] = self._error_code_counts.get(code, 0) + 1

    @property
    def error_code_counts(self) -> dict[str, int]:
        return dict(self._error_code_counts)

    def record_route_duration(self, route: str, duration_seconds: float) -> None:
        self._route_durations.setdefault(route, _RunningAverage()).record(duration_seconds)

    @property
    def route_average_ms(self) -> dict[str, float]:
        return {route: average.average_ms for route, average in self._route_durations.items()}

    def record_node_duration(self, node: str, duration_seconds: float) -> None:
        self._agent_node_durations.setdefault(node, _RunningAverage()).record(duration_seconds)

    @property
    def agent_node_average_ms(self) -> dict[str, float]:
        return {node: average.average_ms for node, average in self._agent_node_durations.items()}
