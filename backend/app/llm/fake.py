"""无网络的 LLM 测试替身。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from app.llm.client import (
    DEFAULT_LLM_CALL_OPTIONS,
    LlmBudget,
    LlmCallOptions,
    LlmFailureKind,
    LlmResult,
    LlmUnavailableError,
)

Behaviour = Literal["normal", "invalid_json", "timeout", "empty", "bad_payload"]


class FakeLlmClient:
    """覆盖正常、非法 JSON、超时、空响应和损坏 payload 五类验收场景。"""

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
        self.call_options: list[LlmCallOptions] = []

    def is_configured(self) -> bool:
        return self._configured

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmResult:
        if not self._configured:
            raise LlmUnavailableError("FakeLlmClient 被构造为未配置")

        budget.charge_call()
        budget.charge(self._tokens_per_call)
        self.calls.append((system, user))
        self.call_options.append(options)

        if self._behaviour == "invalid_json":
            return LlmResult(
                text="这不是 JSON",
                tokens=self._tokens_per_call,
                degraded=False,
                usage_known=True,
            )
        if self._behaviour in {"timeout", "empty"}:
            return LlmResult(
                text=fallback,
                tokens=self._tokens_per_call,
                degraded=True,
                usage_known=True,
            )
        if self._behaviour == "bad_payload":
            # 复刻 DeepSeekLlmClient 对损坏响应体的行为：HTTP 200 但解析失败，
            # 返回的 text 是调用方传入的确定性兜底 JSON，同样合法可解析。
            return LlmResult(
                text=fallback,
                tokens=0,
                degraded=True,
                failure_kind=LlmFailureKind.BAD_PAYLOAD,
                usage_known=False,
            )

        text = self._responses.pop(0) if self._responses else fallback
        return LlmResult(
            text=text,
            tokens=self._tokens_per_call,
            degraded=False,
            usage_known=True,
        )
