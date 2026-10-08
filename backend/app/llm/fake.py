"""无网络的 LLM 测试替身。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal

from app.llm.client import (
    DEFAULT_LLM_CALL_OPTIONS,
    LlmBudget,
    LlmCallOptions,
    LlmFailureKind,
    LlmMessage,
    LlmResult,
    LlmStreamEvent,
    LlmTurn,
    LlmUnavailableError,
    TextDelta,
    ToolSchema,
    TurnComplete,
)

Behaviour = Literal["normal", "invalid_json", "timeout", "empty", "bad_payload"]


class FakeScriptExhaustedError(AssertionError):
    """``turns`` 脚本已耗尽，循环却又调了一次 ``converse()``。

    继承 ``AssertionError``，pytest 会把它当作测试失败而不是错误：脚本耗尽说明循环比
    测试预期多转了一轮，静默编造一个回合只会掩盖这个缺陷。
    """


@dataclass(frozen=True)
class ConverseCall:
    """一次 ``converse()`` 收到的入参快照。"""

    messages: list[LlmMessage]
    tools: list[ToolSchema]
    options: LlmCallOptions


class FakeLlmClient:
    """覆盖正常、非法 JSON、超时、空响应和损坏 payload 五类验收场景。

    v1 的 ``complete()`` 由 ``behaviour`` / ``responses`` 驱动；v2 的 ``converse()`` 由
    ``turns`` 脚本驱动，可编排「先调工具、再作答」这样的多轮序列。两套脚本互相独立。
    """

    def __init__(
        self,
        *,
        behaviour: Behaviour = "normal",
        responses: Sequence[str] = (),
        turns: Sequence[LlmTurn] = (),
        configured: bool = True,
        tokens_per_call: int = 10,
    ) -> None:
        self._behaviour = behaviour
        self._responses = list(responses)
        self._turns = list(turns)
        self._configured = configured
        self._tokens_per_call = tokens_per_call
        self.calls: list[tuple[str, str]] = []
        self.call_options: list[LlmCallOptions] = []
        self.converse_calls: list[ConverseCall] = []

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

    async def converse(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmTurn:
        if not self._configured:
            raise LlmUnavailableError("FakeLlmClient 被构造为未配置")

        # 与真实适配器一致：先扣调用配额，配额耗尽时这次调用没有发生，不留记录。
        budget.charge_call()
        # 快照而非引用：循环会在两轮之间往同一个列表追加消息，测试要看每一轮真正收到了什么。
        self.converse_calls.append(ConverseCall(list(messages), list(tools), options))
        if not self._turns:
            raise FakeScriptExhaustedError(
                f"FakeLlmClient 的 turns 脚本已耗尽：这是第 {len(self.converse_calls)} 次 "
                "converse() 调用，脚本里没有对应的回合"
            )
        turn = self._turns.pop(0)
        budget.charge(turn.tokens)
        return turn

    async def converse_stream(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> AsyncIterator[LlmStreamEvent]:
        turn = await self.converse(messages=messages, tools=tools, budget=budget, options=options)
        # 与真实适配器一致：只有文本产出增量，工具调用只出现在最后的 TurnComplete 里。
        if turn.text:
            yield TextDelta(text=turn.text)
        yield TurnComplete(turn=turn)
