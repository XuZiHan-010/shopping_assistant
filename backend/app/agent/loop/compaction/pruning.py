"""策略一：工具结果清理 `TOOL_RESULT_PRUNING`（PRD A5，契约 §6.12，N4-A Task 2）。

**零 LLM 调用**，行为完全确定。把最近 `keep_recent_rounds` 轮之前的 tool 消息正文**原地**换成
「占位符 + 该调用自己的锚点」：

- 消息条数、角色、`tool_call_id` 与 assistant 的 `tool_calls` 全部不变，两种协议适配器要求的
  「工具结果紧跟其调用」「角色交替」结构因此始终合法；
- 每个被清理的结果就地带上自己的来源、截至时间与草稿版本（`anchors.py`），不另插消息；
- 已清理的消息带 `PRUNED_MARKER`，再次清理时跳过，结果幂等。

回答里数字的确定性校验读的是完整 `ToolResult` 列表，不读消息，清理不会放宽校验。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final

from app.agent.loop.compaction import (
    DEFAULT_KEEP_RECENT_ROUNDS,
    CompactionOutcome,
    CompactionStrategy,
    flatten,
    split_rounds,
)
from app.agent.loop.compaction.anchors import extract_anchors, format_anchors
from app.agent.loop.fencing import fence
from app.llm.client import LlmMessage
from app.localization.locales import SupportedLocale
from app.tools.types import ToolResult

#: 占位符前缀；也是幂等判断的依据。
PRUNED_MARKER: Final = "[工具结果已清理："

_PLACEHOLDER: Final[Mapping[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: PRUNED_MARKER + "{tool}#{call_id}，关键值见下方锚点]",
    SupportedLocale.EN_US: PRUNED_MARKER + "{tool}#{call_id}; key values in the anchors below]",
}


def prune_tool_results(
    messages: Sequence[LlmMessage],
    results: Sequence[ToolResult],
    *,
    locale: SupportedLocale,
    keep_recent_rounds: int = DEFAULT_KEEP_RECENT_ROUNDS,
) -> CompactionOutcome:
    prefix, rounds = split_rounds(messages)
    cutoff = max(len(rounds) - keep_recent_rounds, 0)
    by_call = {result.display.call_id: result for result in results}
    changed = False
    new_rounds: list[list[LlmMessage]] = []
    for index, round_messages in enumerate(rounds):
        if index >= cutoff:
            new_rounds.append(list(round_messages))
            continue
        names = {c.call_id: c.tool_name for c in round_messages[0].tool_calls or ()}
        pruned_round: list[LlmMessage] = []
        for message in round_messages:
            if message.role != "tool" or PRUNED_MARKER in message.content:
                pruned_round.append(message)
                continue
            call_id = message.tool_call_id or ""
            pruned_round.append(
                replace(
                    message,
                    content=_placeholder(names.get(call_id, "tool"), call_id, by_call, locale),
                )
            )
            changed = True
        new_rounds.append(pruned_round)
    return CompactionOutcome(
        messages=flatten(prefix, new_rounds) if changed else list(messages),
        strategy_used=CompactionStrategy.TOOL_RESULT_PRUNING,
        llm_calls=0,
        changed=changed,
    )


def _placeholder(
    tool: str, call_id: str, by_call: Mapping[str, ToolResult], locale: SupportedLocale
) -> str:
    head = _PLACEHOLDER[locale].format(tool=tool, call_id=call_id)
    result = by_call.get(call_id)
    anchors = format_anchors(extract_anchors([result] if result else []), locale)
    body = f"{head}\n{anchors}" if anchors else head
    # 锚点源自工具结果，与原工具消息同等对待：照常围栏（A11）。
    return fence(body, source=f"tool:{tool}")
