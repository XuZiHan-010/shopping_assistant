"""压缩接入工具循环（N4-A Task 4，PRD A5，契约 §6.10 / §6.12）。

- 每次模型决策前估算上下文，超过 `trigger_tokens` 才压缩；未超不动；
- 压缩真的改变了上下文时发出 `ContextCompacted` 事件（SSE `step`），不静默发生；
- 摘要压缩的调用走回合同一份预算：最坏路径恰好不越界，额度用尽后回退到工具结果清理；
- 摘要里的数字不是事实来源：只凭摘要作答会被判无来源并降级；
- 身份（`merchant_id` / `buyer_key`）不进压缩后的提示词。
"""

from __future__ import annotations

import pytest

from app.agent.loop.compaction import CompactionPolicy, CompactionStrategy
from app.agent.loop.compaction.pruning import PRUNED_MARKER
from app.agent.loop.compaction.summarization import SUMMARY_NOTICE
from app.agent.loop.runner import ContextCompacted, LoopEvent, LoopRequest, run_loop
from app.core.config import agent_loop_llm_call_floor
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale
from app.services.quality_types import DegradeReason
from tests.unit.tools.tool_doubles import MERCHANT_ID

from .loop_doubles import (
    ScriptedReviewer,
    build_gates,
    call,
    customer_request,
    end_turn,
    limits,
    merchant_request,
    tool_use_turn,
)

ZH = SupportedLocale.ZH_CN


def _policy(
    strategy: CompactionStrategy = CompactionStrategy.TOOL_RESULT_PRUNING,
    *,
    trigger_tokens: int = 1,
    max_calls: int = 1,
    keep_recent_rounds: int = 1,
) -> CompactionPolicy:
    return CompactionPolicy(
        strategy=strategy,
        trigger_tokens=trigger_tokens,
        max_calls=max_calls,
        keep_recent_rounds=keep_recent_rounds,
    )


def _summary(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _reads(n: int) -> list[LlmTurn]:
    return [tool_use_turn(call("slow_read", label=f"r{i}")) for i in range(n)]


async def _run(llm: FakeLlmClient, request: LoopRequest | None = None, **kwargs: object):  # type: ignore[no-untyped-def]
    gates = build_gates()[0]
    request = request or merchant_request()
    return await run_loop(
        request,
        llm=llm,
        gates=gates,
        tools=gates.registry.schemas_for(request.context.session.role),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_over_threshold_prunes_older_tool_results_and_emits_step() -> None:
    events: list[LoopEvent] = []

    async def sink(event: LoopEvent) -> None:
        events.append(event)

    llm = FakeLlmClient(turns=[*_reads(3), end_turn("整理好了。")])

    out = await _run(llm, limits=limits(compaction=_policy()), on_event=sink)

    assert out.stop_reason == "COMPLETED"
    last = llm.converse_calls[-1].messages
    tools = [m for m in last if m.role == "tool"]
    assert PRUNED_MARKER in tools[0].content and PRUNED_MARKER in tools[1].content
    assert PRUNED_MARKER not in tools[2].content  # 最近一轮原样保留
    compacted = [e for e in events if isinstance(e, ContextCompacted)]
    assert compacted and compacted[0].strategy is CompactionStrategy.TOOL_RESULT_PRUNING
    assert out.compactions == [e.strategy for e in compacted]
    assert out.llm_calls == 4  # 清理零 LLM 调用


async def test_under_threshold_nothing_is_compacted() -> None:
    events: list[LoopEvent] = []

    async def sink(event: LoopEvent) -> None:
        events.append(event)

    llm = FakeLlmClient(turns=[*_reads(3), end_turn("整理好了。")])

    out = await _run(
        llm, limits=limits(compaction=_policy(trigger_tokens=1_000_000)), on_event=sink
    )

    assert all(PRUNED_MARKER not in m.content for c in llm.converse_calls for m in c.messages)
    assert not [e for e in events if isinstance(e, ContextCompacted)]
    assert out.compactions == []


async def test_without_policy_loop_never_compacts() -> None:
    llm = FakeLlmClient(turns=[*_reads(3), end_turn("整理好了。")])

    out = await _run(llm, limits=limits())

    assert out.compactions == []
    assert all(PRUNED_MARKER not in m.content for c in llm.converse_calls for m in c.messages)


async def test_summarization_uses_one_call_then_falls_back_to_pruning() -> None:
    # r0、r1 → 第 3 次决策前摘要（1 次调用）→ r2 → 第 4 次决策前额度已用尽，回退清理。
    llm = FakeLlmClient(
        turns=[*_reads(2), _summary("商家在拆解经营数据。"), *_reads(2), end_turn("整理好了。")]
    )

    out = await _run(
        llm,
        limits=limits(compaction=_policy(CompactionStrategy.SUMMARIZATION, max_calls=1)),
    )

    assert out.stop_reason == "COMPLETED"
    assert out.compactions[0] is CompactionStrategy.SUMMARIZATION
    assert set(out.compactions[1:]) == {CompactionStrategy.TOOL_RESULT_PRUNING}
    summary_calls = [c for c in llm.converse_calls if c.tools == []]
    assert len(summary_calls) == 1  # 摘要调用不给工具，且只发生一次
    assert out.llm_calls == 6  # 5 次决策 + 1 次摘要
    assert SUMMARY_NOTICE[ZH] in llm.converse_calls[-1].messages[1].content


async def test_worst_path_with_summarization_fits_budget_exactly() -> None:
    """§6.10：每轮都调工具、压缩达到上限、每次质量尝试都生成且复核——恰好不越界。"""

    floor = agent_loop_llm_call_floor(max_turns=4, compaction_max_calls=1, quality_max_attempts=2)
    llm = FakeLlmClient(
        turns=[
            *_reads(2),
            _summary("早期对话。"),
            *_reads(1),
            end_turn("第一次回答"),
            end_turn("修正后的回答"),
        ]
    )
    reviewer = ScriptedReviewer(verdicts=[False, True])

    out = await _run(
        llm,
        limits=limits(
            max_turns=4,
            max_llm_calls=floor,
            compaction=_policy(CompactionStrategy.SUMMARIZATION, max_calls=1),
        ),
        reviewer=reviewer,
    )

    assert out.stop_reason == "COMPLETED"
    assert out.llm_calls == floor == 8
    assert out.answer == "修正后的回答"


async def test_number_only_in_summary_is_rejected_downstream() -> None:
    """A5：摘要不得升级为事实来源。"""

    llm = FakeLlmClient(
        turns=[
            *_reads(2),
            _summary("商家说上月净成交额大约 777 万。"),
            end_turn("净成交额是 777 万"),
            end_turn("净成交额是 777 万"),
        ]
    )

    out = await _run(
        llm,
        limits=limits(compaction=_policy(CompactionStrategy.SUMMARIZATION)),
    )

    assert out.degraded is True
    assert out.degraded_reason is DegradeReason.VALIDATION
    assert "777" not in out.answer


@pytest.mark.parametrize("strategy", list(CompactionStrategy))
async def test_identity_never_enters_compacted_prompt(strategy: CompactionStrategy) -> None:
    llm = FakeLlmClient(turns=[*_reads(2), _summary("早期对话。"), *_reads(1), end_turn("好。")])
    request = customer_request()

    await _run(llm, request, limits=limits(compaction=_policy(strategy)))

    session = request.context.session
    secrets = [str(MERCHANT_ID), session.buyer_key]
    for sent in llm.converse_calls:
        for message in sent.messages:
            for secret in secrets:
                assert secret and secret not in message.content
