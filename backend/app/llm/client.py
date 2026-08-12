"""LLM 协议与单请求预算。

沿用参考实现的 ``is_configured()`` 和显式 ``fallback`` 接缝，并增加本项目
要求的调用次数与 token 预算。预算耗尽由调用方转成可见降级，而非错误页面。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LlmUnavailableError(RuntimeError):
    """密钥或适配器不可用，调用方应使用 fallback。"""


class LlmBudgetError(RuntimeError):
    """所有 LLM 预算耗尽异常的基类。"""


class LlmBudgetExceededError(LlmBudgetError):
    """单请求的模型调用次数或 token 已超过上限。"""


class LlmDailyBudgetExceededError(LlmBudgetError):
    """每日全局 LLM 费用预算已耗尽。"""


@dataclass
class LlmBudget:
    max_calls: int
    max_tokens: int
    calls: int = 0
    tokens: int = 0

    def charge_call(self) -> None:
        if self.calls >= self.max_calls:
            raise LlmBudgetExceededError(f"单请求 LLM 调用次数已达上限 {self.max_calls}")
        self.calls += 1

    def charge(self, tokens: int) -> None:
        if self.tokens + tokens > self.max_tokens:
            raise LlmBudgetExceededError(f"单请求 LLM token 已达上限 {self.max_tokens}")
        self.tokens += tokens


@dataclass(frozen=True)
class LlmResult:
    text: str
    tokens: int
    degraded: bool


class LlmClient(Protocol):
    def is_configured(self) -> bool: ...

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
    ) -> LlmResult: ...
