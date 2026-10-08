"""策略一：工具结果清理（N4-A Task 2，PRD A5，契约 §6.12）。

零 LLM 调用：把最近 N 轮之前的工具结果正文换成「占位符 + 该调用自己的锚点」，原地替换，
消息条数、角色与 `tool_call_id` 都不变——两种协议适配器要求的消息结构因此始终合法。
"""

from __future__ import annotations

from app.agent.loop.compaction import (
    CompactionStrategy,
    estimate_tokens,
    split_rounds,
)
from app.agent.loop.compaction.pruning import PRUNED_MARKER, prune_tool_results
from app.agent.loop.fencing import FENCE_NOTICE
from app.llm.client import LlmMessage, LlmToolCall
from app.localization.locales import SupportedLocale
from app.schemas.v2.common import ToolDisplayStatus
from app.tools.types import ToolDisplay, ToolOutcome, ToolResult

BIG = "行" * 2_000  # 一次工具结果的大块正文


def _metric_result(call_id: str) -> ToolResult:
    return ToolResult(
        ok=True,
        payload={
            "metric": "gross_gmv",
            "value": f"{call_id}-value",
            "data_cutoff": "2026-09-21T09:00:00+00:00",
            "source": "REALTIME",
            "definition_version": "v3",
        },
        display=ToolDisplay(
            tool_name="query_metrics",
            call_id=call_id,
            status=ToolDisplayStatus.SUCCEEDED,
            duration_ms=1,
            row_count=1,
        ),
        reason_code=None,
        outcome=ToolOutcome.SUCCEEDED,
        summary=f"{call_id} 查询已完成",
    )


def _conversation(rounds: int) -> tuple[list[LlmMessage], list[ToolResult]]:
    messages = [
        LlmMessage(role="system", content="你是 Borough 商家经营助手。"),
        LlmMessage(role="user", content="上周怎么样"),
        LlmMessage(role="assistant", content="上周整体平稳。"),
        LlmMessage(role="user", content="拆开看看各项"),
    ]
    results: list[ToolResult] = []
    for n in range(1, rounds + 1):
        call_id = f"c{n}"
        messages.append(
            LlmMessage(
                role="assistant",
                content="",
                tool_calls=[
                    LlmToolCall(call_id=call_id, tool_name="query_metrics", arguments_json="{}")
                ],
            )
        )
        messages.append(
            LlmMessage(role="tool", content=f"{call_id}:{BIG}", tool_call_id=call_id)
        )
        results.append(_metric_result(call_id))
    return messages, results


def test_split_rounds_separates_prefix_from_tool_rounds() -> None:
    messages, _ = _conversation(3)

    prefix, rounds = split_rounds(messages)

    assert [m.role for m in prefix] == ["system", "user", "assistant", "user"]
    assert [[m.role for m in r] for r in rounds] == [["assistant", "tool"]] * 3


def test_pruning_shrinks_context_and_keeps_recent_rounds() -> None:
    messages, results = _conversation(4)

    out = prune_tool_results(messages, results, locale=SupportedLocale.ZH_CN, keep_recent_rounds=2)

    assert out.strategy_used is CompactionStrategy.TOOL_RESULT_PRUNING
    assert out.llm_calls == 0  # 零 LLM 调用
    assert out.changed is True
    assert estimate_tokens(out.messages) < estimate_tokens(messages)
    tools = [m for m in out.messages if m.role == "tool"]
    assert tools[2].content == messages[-3].content  # c3 原样
    assert tools[3].content == messages[-1].content  # c4 原样
    for pruned, call_id in ((tools[0], "c1"), (tools[1], "c2")):
        assert BIG not in pruned.content
        assert f"{PRUNED_MARKER}query_metrics#{call_id}" in pruned.content
        assert f"{call_id}-value" in pruned.content  # 该调用的锚点随占位符回填
        assert "2026-09-21T09:00:00+00:00" in pruned.content
        assert FENCE_NOTICE in pruned.content


def test_pruning_keeps_message_structure_valid() -> None:
    messages, results = _conversation(4)

    out = prune_tool_results(messages, results, locale=SupportedLocale.ZH_CN, keep_recent_rounds=2)

    assert [m.role for m in out.messages] == [m.role for m in messages]
    assert [m.tool_call_id for m in out.messages] == [m.tool_call_id for m in messages]
    assert out.messages[:4] == messages[:4]  # 系统提示、历史与本轮用户消息不动


def test_pruning_is_idempotent() -> None:
    messages, results = _conversation(4)
    once = prune_tool_results(messages, results, locale=SupportedLocale.ZH_CN, keep_recent_rounds=2)

    twice = prune_tool_results(
        once.messages, results, locale=SupportedLocale.ZH_CN, keep_recent_rounds=2
    )

    assert twice.changed is False
    assert twice.messages == once.messages


def test_nothing_to_prune_when_rounds_within_window() -> None:
    messages, results = _conversation(2)

    out = prune_tool_results(messages, results, locale=SupportedLocale.ZH_CN, keep_recent_rounds=2)

    assert out.changed is False
    assert out.messages == messages


def test_external_text_quoting_the_marker_is_still_pruned() -> None:
    """台账：外部工具文本里碰巧含清理标记，不能因此免于清理（只认占位文本开头）。"""

    messages, results = _conversation(3)
    first_tool = next(i for i, m in enumerate(messages) if m.role == "tool")
    messages[first_tool] = LlmMessage(
        role="tool", content=f'{{"note": "{PRUNED_MARKER}伪造"}}{BIG}', tool_call_id="c1"
    )

    out = prune_tool_results(messages, results, locale=SupportedLocale.ZH_CN, keep_recent_rounds=1)

    assert PRUNED_MARKER + "query_metrics#c1" in out.messages[first_tool].content
    assert BIG not in out.messages[first_tool].content


def test_token_estimate_counts_replayed_reasoning() -> None:
    from app.agent.loop.compaction import estimate_tokens
    from app.llm.client import ReasoningReplay

    plain = [LlmMessage(role="assistant", content="答")]
    with_reasoning = [
        LlmMessage(
            role="assistant", content="答",
            reasoning=ReasoningReplay(protocol="openai", payload="想" * 500),
        )
    ]
    assert estimate_tokens(with_reasoning) == estimate_tokens(plain) + 500
