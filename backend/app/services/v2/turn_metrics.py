"""v2 对话回合的运维计数：顾客端与商家端共用同一个入口。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.agent.loop.runner import LoopOutcome
from app.core.metrics import OperationalMetrics


def record_turn_metrics(
    metrics: OperationalMetrics | None, outcome: LoopOutcome, sources: Iterable[Any]
) -> None:
    """把一个跑完的 v2 回合记进运维指标（PRD §10.4）。

    只在工具循环正常返回后调用一次：幂等重放不会再进到这里，致命错误走错误码计数。
    `sources` 是最终响应的 `analysis_sources`，用来统计「没有整轮降级、但某个来源降级」的回合。
    """

    if metrics is None:
        return
    metrics.record_turn(
        degraded=outcome.degraded,
        reason=outcome.degraded_reason.value if outcome.degraded_reason is not None else None,
        degraded_sources=[str(entry.source.value) for entry in sources if entry.degraded],
    )
