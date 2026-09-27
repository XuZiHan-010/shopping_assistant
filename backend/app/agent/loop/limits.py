"""循环五项上限（§6.10，PRD A2）：轮数、工具调用、LLM 调用、墙钟时间、token 同时生效。

预算公式本身定义在 `app.core.config.agent_loop_llm_call_floor()`，由 `Settings` 在启动时校验；
`core` 不反向依赖 `agent`，所以公式住在配置层，这里只负责把配置变成一个回合的上限与预算。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

from app.llm.client import LlmBudget

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True)
class LoopLimits:
    max_turns: int  # 循环轮数（每轮一次决策调用）
    max_tool_calls: int  # 工具调用总次数
    max_llm_calls: int  # 本回合 LlmBudget 的调用上限，取 AGENT_LOOP_MAX_LLM_CALLS
    wall_clock_seconds: float
    max_tokens: int  # 本回合 LlmBudget 的 token 上限
    #: 质量尝试次数（生成 + 独立 Reviewer 为一次）。它是预算公式的加数，放在这里而不是
    #: 让循环另读配置，保证「上限」与「为上限配的预算」来自同一个对象。
    quality_max_attempts: int = 2
    #: 单回合 `load_skill` 次数上限（PRD A4）；超限的调用被拒绝并告知模型，回合继续。
    max_skill_loads: int = 3

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if value <= 0:
                raise ValueError(f"LoopLimits.{item.name} 必须为正数，实际为 {value}")

    @classmethod
    def from_settings(cls, settings: Settings) -> LoopLimits:
        return cls(
            max_turns=settings.agent_loop_max_turns,
            max_tool_calls=settings.agent_loop_max_tool_calls,
            max_llm_calls=settings.agent_loop_max_llm_calls,
            wall_clock_seconds=settings.agent_loop_wall_clock_seconds,
            max_tokens=settings.llm_max_tokens_per_request,
            quality_max_attempts=settings.agent_loop_quality_max_attempts,
            max_skill_loads=settings.skill_max_per_turn,
        )

    def new_budget(self) -> LlmBudget:
        """每个回合一份新预算；决策、重新生成与 Reviewer 共用它。"""

        return LlmBudget(max_calls=self.max_llm_calls, max_tokens=self.max_tokens)
