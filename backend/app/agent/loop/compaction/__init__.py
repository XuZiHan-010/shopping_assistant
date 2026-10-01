"""工具循环内的上下文压缩（PRD A5，契约 §6.12，N4-A）。

压缩随循环实现，不单独建顶层目录（`docs/project-navigation.md` §5.3.1）。两种策略产出同一种
`CompactionOutcome`，由 `COMPACTION_STRATEGY` 选择；锚点（`anchors.py`）两者共用。

消息的形状（循环 `_initial_messages()` 与工具轮追加的结果）::

    [system, (历史 user / assistant 文字)…, 本轮 user, (assistant+tool_calls, tool…)…]
     └──────────────────── prefix ────────────────────┘ └──────── rounds ────────┘

一「轮」是一条带 `tool_calls` 的 assistant 消息及其后的全部 tool 消息。两种策略都只动较早的轮
（摘要压缩另外吸收历史文字），最近 `keep_recent_rounds` 轮与系统提示原样保留。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.llm.client import LlmMessage
from app.localization.locales import SupportedLocale
from app.schemas.chat import ThinkingStep


class CompactionStrategy(StrEnum):
    TOOL_RESULT_PRUNING = "TOOL_RESULT_PRUNING"  # 工具结果清理（零 LLM 调用）
    SUMMARIZATION = "SUMMARIZATION"  # 摘要压缩（消耗 1 次 LLM 调用）


#: 最近几轮的工具结果原样保留：模型下一步通常就要消费它们。
DEFAULT_KEEP_RECENT_ROUNDS = 2


@dataclass(frozen=True)
class CompactionPolicy:
    """一个回合的压缩配置（`COMPACTION_*`）。循环在每次模型决策前按它判断是否压缩。

    `max_calls` 只约束摘要压缩的 LLM 调用；它已计入 `AGENT_LOOP_MAX_LLM_CALLS` 的预算公式（§6.10），
    用尽后改用零调用的工具结果清理，不会突破回合总上限。
    """

    strategy: CompactionStrategy
    trigger_tokens: int
    max_calls: int
    keep_recent_rounds: int = DEFAULT_KEEP_RECENT_ROUNDS

    def __post_init__(self) -> None:
        if self.trigger_tokens <= 0:
            raise ValueError(
                f"CompactionPolicy.trigger_tokens 必须为正数，实际为 {self.trigger_tokens}"
            )
        if self.max_calls < 0:
            raise ValueError(f"CompactionPolicy.max_calls 不能为负，实际为 {self.max_calls}")
        if self.keep_recent_rounds < 0:
            raise ValueError(
                f"CompactionPolicy.keep_recent_rounds 不能为负，实际为 {self.keep_recent_rounds}"
            )


#: 压缩发生时告知用户的处理阶段（SSE `step` 与最终响应的 `thinking_steps`），不静默发生。
COMPACTION_STEP_NODE: Final = "compact_context"
_COMPACTION_STEP_LABEL: Final[Mapping[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: "正在整理较早的对话",
    SupportedLocale.EN_US: "Condensing the earlier conversation",
}


def compaction_step(locale: SupportedLocale) -> ThinkingStep:
    return ThinkingStep(label=_COMPACTION_STEP_LABEL[locale], node=COMPACTION_STEP_NODE)


@dataclass(frozen=True)
class CompactionOutcome:
    messages: list[LlmMessage]
    strategy_used: CompactionStrategy
    llm_calls: int
    changed: bool


def estimate_tokens(messages: Sequence[LlmMessage]) -> int:
    """保守估算：按字符计。中文约一字一 token，英文偏高估——宁可早压缩也不超限。

    与 `app.llm.guard.estimate_call_tokens` 同口径（字符数），两处阈值才可比。
    """

    total = 0
    for message in messages:
        total += len(message.content)
        for call in message.tool_calls or ():
            total += len(call.tool_name) + len(call.arguments_json)
    return total


def split_rounds(
    messages: Sequence[LlmMessage],
) -> tuple[list[LlmMessage], list[list[LlmMessage]]]:
    """切成 prefix（系统提示、历史、本轮用户消息）与按顺序的工具轮。"""

    start = next(
        (i for i, m in enumerate(messages) if m.role == "assistant" and m.tool_calls),
        len(messages),
    )
    prefix = list(messages[:start])
    rounds: list[list[LlmMessage]] = []
    for message in messages[start:]:
        if message.role == "assistant" and message.tool_calls:
            rounds.append([message])
        elif rounds:
            rounds[-1].append(message)
        else:  # pragma: no cover - start 之后的第一条必然开启一轮
            prefix.append(message)
    return prefix, rounds


def flatten(
    prefix: Sequence[LlmMessage], rounds: Sequence[Sequence[LlmMessage]]
) -> list[LlmMessage]:
    return [*prefix, *(m for r in rounds for m in r)]
