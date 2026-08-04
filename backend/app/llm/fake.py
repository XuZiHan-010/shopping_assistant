"""无网络的 LLM 测试替身。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from app.llm.client import LlmBudget, LlmResult, LlmUnavailableError

Behaviour = Literal["normal", "invalid_json", "timeout", "empty"]


class FakeLlmClient:
    """覆盖正常、非法 JSON、超时和空响应四类 B3 验收场景。"""

    def __init__(
        self,
        *,
        behaviour: Behaviour = "normal",
        responses: Sequence[str] = (),
        configured: bool = True,
        tokens_per_call: int = 10,
    ) -> None:
        self._behaviour = behaviour
        self._responses = list(responses)
        self._configured = configured
        self._tokens_per_call = tokens_per_call
        self.calls: list[tuple[str, str]] = []

    def is_configured(self) -> bool:
        return self._configured

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
    ) -> LlmResult:
        if not self._configured:
            raise LlmUnavailableError("FakeLlmClient 被构造为未配置")

        budget.charge_call()
        budget.charge(self._tokens_per_call)
        self.calls.append((system, user))

        if self._behaviour == "invalid_json":
            return LlmResult(text="这不是 JSON", tokens=self._tokens_per_call, degraded=False)
        if self._behaviour in {"timeout", "empty"}:
            return LlmResult(text=fallback, tokens=self._tokens_per_call, degraded=True)

        text = self._responses.pop(0) if self._responses else fallback
        return LlmResult(text=text, tokens=self._tokens_per_call, degraded=False)
