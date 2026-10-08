"""进程内运维指标：限流命中、降级次数、错误码分布、路由与 Agent 节点耗时。

和 ``app.core.rate_limit.SlidingWindowRateLimiter`` 共享同一份约束：不落库、
进程重启归零，多实例部署下互不同步，只是近似值——见 ``docs/deployment.md``。
``GET /api/admin/ops/status``（B7 运维端点）是这份数据唯一的消费方。
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

ROUTE_SAMPLE_WINDOW: Final = 500
"""p95 只看每条路由最近这么多次请求：既反映当前状态，内存也有上界。"""


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
        self._degraded_reason_counts: dict[str, int] = {}
        self._source_degraded_counts: dict[str, int] = {}
        self._error_code_counts: dict[str, int] = {}
        self._route_durations: dict[str, _RunningAverage] = {}
        self._route_samples: dict[str, deque[float]] = {}
        self.tool_calls_total = 0
        self.tool_errors_total = 0
        self._agent_node_durations: dict[str, _RunningAverage] = {}

    def record_error_code(self, code: str) -> None:
        self._error_code_counts[code] = self._error_code_counts.get(code, 0) + 1

    @property
    def error_code_counts(self) -> dict[str, int]:
        return dict(self._error_code_counts)

    def record_route_duration(self, route: str, duration_seconds: float) -> None:
        self._route_durations.setdefault(route, _RunningAverage()).record(duration_seconds)
        samples = self._route_samples.setdefault(route, deque(maxlen=ROUTE_SAMPLE_WINDOW))
        samples.append(duration_seconds)

    @property
    def route_p95_ms(self) -> dict[str, float]:
        """最近窗口内的 p95（最近秩法）；进程内近似值，多实例不同步。"""

        result: dict[str, float] = {}
        for route, samples in self._route_samples.items():
            ordered = sorted(samples)
            rank = max(math.ceil(0.95 * len(ordered)) - 1, 0)
            result[route] = ordered[rank] * 1000
        return result

    def record_turn(
        self, *, degraded: bool, reason: str | None, degraded_sources: Iterable[str]
    ) -> None:
        """记一个已完成的对话回合（PRD §10.4：降级按整轮与单来源分开）。

        整轮降级按原因码计数，各原因之和恒等于 `degraded_count`；回答没有整轮降级、
        只是某个来源降级（例如规则检索退回关键词）的，另记在按来源的计数里。
        """

        if degraded:
            self.degraded_count += 1
            key = reason or "UNKNOWN"
            self._degraded_reason_counts[key] = self._degraded_reason_counts.get(key, 0) + 1
            return
        for source in degraded_sources:
            self._source_degraded_counts[source] = self._source_degraded_counts.get(source, 0) + 1

    @property
    def degraded_reason_counts(self) -> dict[str, int]:
        return dict(self._degraded_reason_counts)

    @property
    def source_degraded_counts(self) -> dict[str, int]:
        return dict(self._source_degraded_counts)

    def record_tool_call(self, *, ok: bool) -> None:
        self.tool_calls_total += 1
        if not ok:
            self.tool_errors_total += 1

    @property
    def route_average_ms(self) -> dict[str, float]:
        return {route: average.average_ms for route, average in self._route_durations.items()}

    def record_node_duration(self, node: str, duration_seconds: float) -> None:
        self._agent_node_durations.setdefault(node, _RunningAverage()).record(duration_seconds)

    @property
    def agent_node_average_ms(self) -> dict[str, float]:
        return {node: average.average_ms for node, average in self._agent_node_durations.items()}
