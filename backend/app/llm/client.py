"""LLM 协议与单请求预算。

沿用参考实现的 ``is_configured()`` 和显式 ``fallback`` 接缝，并增加本项目
要求的调用次数与 token 预算。预算耗尽由调用方转成可见降级，而非错误页面。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol


class LlmUnavailableError(RuntimeError):
    """密钥或适配器不可用，调用方应使用 fallback。"""


class LlmBudgetError(RuntimeError):
    """所有 LLM 预算耗尽异常的基类。"""


class LlmBudgetExceededError(LlmBudgetError):
    """单请求的模型调用次数或 token 已超过上限。"""


class LlmDailyBudgetExceededError(LlmBudgetError):
    """每日全局 LLM 费用预算已耗尽。"""


class LlmFailureKind(StrEnum):
    """可安全记录和对外归因的上游失败类型。"""

    HTTP_401 = "HTTP_401"
    HTTP_403 = "HTTP_403"
    HTTP_429 = "HTTP_429"
    HTTP_OTHER = "HTTP_OTHER"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    BAD_PAYLOAD = "BAD_PAYLOAD"


@dataclass(frozen=True)
class LlmCallOptions:
    """单次模型调用的可选上游能力，默认保持普通对话行为。"""

    json_output: bool = False
    thinking: Literal["enabled", "disabled"] = "enabled"
    # Guard 可按本次剩余的总 token 预算进一步收紧生成上限。
    max_output_tokens: int | None = None


STRUCTURED_CALL_OPTIONS = LlmCallOptions(json_output=True, thinking="disabled")
DEFAULT_LLM_CALL_OPTIONS = LlmCallOptions()


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
    input_tokens: int = 0
    output_tokens: int = 0
    failure_kind: LlmFailureKind | None = None
    usage_known: bool = False


class LlmClient(Protocol):
    def is_configured(self) -> bool: ...

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmResult: ...


# ---------------------------------------------------------------------------
# 工具调用与流式（N1 模块 B）。
#
# 以下全部是新增：`complete()` 及其数据类保持原样，v1 链路继续使用它。
# `LlmClient` 本身不加方法——`LlmCostGuard` 等 v1 实现按结构满足它，给它加方法
# 会让它们集体失去资格；工具调用能力由下方的子协议承载。
# ---------------------------------------------------------------------------

LlmProtocolName = Literal["openai", "anthropic"]


@dataclass(frozen=True)
class ReasoningReplay:
    """上一轮的推理内容，原样回放给**同一协议**。适配器之外不解读它。

    DeepSeek 文档要求：思考模式下带 ``tools`` 的多轮请求须把之前每一轮 assistant 的推理内容
    完整回传（文档称否则 400；2026-09-22 实测 ``deepseek-flash`` 两协议省略后都未被拒，
    但仍按文档回传，以防上游收紧）。载荷格式随协议而异，因此绑定协议名，跨协议回放会被拒绝。
    """

    protocol: LlmProtocolName
    payload: str  # OpenAI：reasoning_content；Anthropic：thinking 块列表的 JSON


@dataclass(frozen=True)
class LlmToolCall:
    call_id: str
    tool_name: str
    # 原始串，不解析：解析与校验是工具注册表的职责（R4）。适配器若自作主张 json.loads()
    # 并吞掉异常，畸形参数就会以「空字典」的面目进入工具，而不是被闸门拦下。
    arguments_json: str


@dataclass(frozen=True)
class LlmMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None  # role="tool" 时必填
    tool_calls: list[LlmToolCall] | None = None  # role="assistant" 时可能有
    reasoning: ReasoningReplay | None = None  # role="assistant" 时由上一轮 LlmTurn 带回

    def __post_init__(self) -> None:
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("role=tool 的消息必须带 tool_call_id")


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, object]  # JSON Schema，由 Pydantic 模型导出


LlmStopReason = Literal["END_TURN", "TOOL_USE", "MAX_TOKENS", "ERROR"]


@dataclass(frozen=True)
class LlmTurn:
    """一次模型回合的结果，两种协议下形状完全一致。"""

    text: str | None
    tool_calls: list[LlmToolCall]
    stop_reason: LlmStopReason
    tokens: int
    input_tokens: int = 0
    output_tokens: int = 0
    degraded: bool = False
    failure_kind: LlmFailureKind | None = None
    usage_known: bool = False
    # None = 提供方未上报，不等于 0：记成 0 会让成本估算误以为全部未命中。
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None
    reasoning: ReasoningReplay | None = None

    def __post_init__(self) -> None:
        if self.stop_reason == "TOOL_USE" and not self.tool_calls:
            raise ValueError("stop_reason=TOOL_USE 的回合必须带 tool_calls")
        if self.stop_reason == "END_TURN" and self.text is None:
            raise ValueError("stop_reason=END_TURN 的回合必须带 text")


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class TurnComplete:
    turn: LlmTurn  # 与 converse() 的返回值同构


LlmStreamEvent = TextDelta | TurnComplete


class ConversationalLlmClient(LlmClient, Protocol):
    """支持工具调用与流式的模型客户端；v2 工具循环依赖它。

    `converse_stream()` 的约定：

    - 文本增量逐段产出 ``TextDelta``；**工具调用不产出增量**——参数分片在适配器内拼完，
      只在最后的 ``TurnComplete.turn.tool_calls`` 出现，半截参数交给上层没有用处，还可能被误执行；
    - 流以且仅以一个 ``TurnComplete`` 结束；中途断流时它携带降级结果
      （``stop_reason="ERROR"``、``degraded=True``、``tool_calls=[]``），已收到的工具调用分片一律丢弃。
    """

    async def converse(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmTurn: ...

    def converse_stream(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> AsyncIterator[LlmStreamEvent]: ...
