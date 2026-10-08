"""策略二：摘要压缩（N4-A Task 3，PRD A5，契约 §6.12）。

- 摘要只替代对话叙述，锚点**另行回填**，不交给摘要「顺便保留」；
- 摘要显式标注为模型生成内容、不是事实来源，下游确定性校验不接受它作数字来源；
- 每次压缩 1 次 LLM 调用，额度用尽、模型不可用或返回空时回退到工具结果清理；
- 被摘要的原文整体围栏后再交给摘要模型（A11）。
"""

from __future__ import annotations

import pytest

from app.agent.loop.checks import ungrounded_numbers
from app.agent.loop.compaction import CompactionStrategy, split_rounds
from app.agent.loop.compaction.summarization import SUMMARY_NOTICE, summarize_early_context
from app.agent.loop.fencing import FENCE_NOTICE
from app.llm.client import LlmBudget, LlmTurn
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale

from .test_compaction_pruning import BIG, _conversation

ZH = SupportedLocale.ZH_CN


def _summary(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=12, max_tokens=100_000)


async def test_summary_is_marked_model_generated_and_replaces_early_context() -> None:
    messages, results = _conversation(4)
    llm = FakeLlmClient(turns=[_summary("商家想按指标拆解上周表现。")])

    out = await summarize_early_context(
        messages, results, llm=llm, budget=_budget(), locale=ZH, remaining_calls=1
    )

    assert out.strategy_used is CompactionStrategy.SUMMARIZATION
    assert out.llm_calls == 1 and out.changed is True
    # 历史与较早两轮被吸收；结构：系统提示 → 本轮用户消息（前置摘要）→ 最近两轮。
    assert [m.role for m in out.messages] == [
        "system", "user", "assistant", "tool", "assistant", "tool",
    ]
    rebuilt = out.messages[1].content
    assert SUMMARY_NOTICE[ZH] in rebuilt and "不是事实来源" in rebuilt
    assert "商家想按指标拆解上周表现。" in rebuilt
    assert rebuilt.endswith("拆开看看各项")  # 本轮用户原话保留在最后
    assert out.messages[-1] == messages[-1] and out.messages[-3] == messages[-3]


async def test_anchors_survive_even_if_summary_drops_everything() -> None:
    """锚点靠回填保留，不靠摘要质量：脚本故意返回一句什么都没保留的摘要。"""

    messages, results = _conversation(4)
    llm = FakeLlmClient(turns=[_summary("早期对话。")])

    out = await summarize_early_context(
        messages, results, llm=llm, budget=_budget(), locale=ZH, remaining_calls=1
    )

    rebuilt = out.messages[1].content
    for call_id in ("c1", "c2"):  # 被摘要吸收的两轮
        assert f"query_metrics#{call_id}" in rebuilt and f"{call_id}-value" in rebuilt
    assert "2026-09-21T09:00:00+00:00" in rebuilt and "v3" in rebuilt


async def test_transcript_is_fenced_and_summarizer_gets_no_tools() -> None:
    messages, results = _conversation(4)
    llm = FakeLlmClient(turns=[_summary("摘要。")])

    await summarize_early_context(
        messages, results, llm=llm, budget=_budget(), locale=ZH, remaining_calls=1
    )

    call = llm.converse_calls[0]
    assert call.tools == []
    assert FENCE_NOTICE in call.messages[-1].content
    assert BIG in call.messages[-1].content  # 被摘要的是原文，不是已经清理过的占位符


async def test_number_only_in_summary_is_not_a_source() -> None:
    """A5：摘要不得升级为事实来源——校验的来源里没有摘要文字。"""

    messages, results = _conversation(4)
    llm = FakeLlmClient(turns=[_summary("商家说上月净成交额大约 777 万。")])
    out = await summarize_early_context(
        messages, results, llm=llm, budget=_budget(), locale=ZH, remaining_calls=1
    )
    assert "777" in out.messages[1].content

    sources = [messages[0].content, messages[3].content]  # 系统提示与本轮用户原话
    assert ungrounded_numbers("净成交额是 777 万", results, sources=sources) == ["777万"]


async def test_no_compaction_calls_left_falls_back_to_pruning() -> None:
    messages, results = _conversation(4)
    llm = FakeLlmClient(turns=[_summary("不会被调用")])

    out = await summarize_early_context(
        messages, results, llm=llm, budget=_budget(), locale=ZH, remaining_calls=0
    )

    assert out.strategy_used is CompactionStrategy.TOOL_RESULT_PRUNING
    assert out.llm_calls == 0 and llm.converse_calls == []


@pytest.mark.parametrize(
    "llm",
    [
        FakeLlmClient(configured=False),  # 模型不可用
        FakeLlmClient(turns=[_summary("   ")]),  # 空摘要
        FakeLlmClient(
            turns=[
                LlmTurn(text="x", tool_calls=[], stop_reason="END_TURN", tokens=0, degraded=True)
            ]
        ),
    ],
)
async def test_failed_summary_falls_back_to_pruning(llm: FakeLlmClient) -> None:
    messages, results = _conversation(4)

    out = await summarize_early_context(
        messages, results, llm=llm, budget=_budget(), locale=ZH, remaining_calls=1
    )

    assert out.strategy_used is CompactionStrategy.TOOL_RESULT_PRUNING
    assert out.changed is True  # 清理照常生效，回合不因摘要失败而中断
    _prefix, rounds = split_rounds(out.messages)
    assert len(rounds) == 4


async def test_nothing_to_summarize_leaves_messages_untouched() -> None:
    messages, results = _conversation(2)
    messages = [messages[0], messages[3], *messages[4:]]  # 没有历史，只有最近两轮
    llm = FakeLlmClient(turns=[_summary("不会被调用")])

    out = await summarize_early_context(
        messages, results, llm=llm, budget=_budget(), locale=ZH, remaining_calls=1
    )

    assert out.changed is False and out.llm_calls == 0
    assert out.messages == messages and llm.converse_calls == []


async def test_summary_with_tool_call_markup_is_not_used() -> None:
    """台账：摘要正文混进上游内部工具调用标记时与主循环同样不采用，回退到工具结果清理。"""

    messages, results = _conversation(4)
    llm = FakeLlmClient(turns=[_summary("摘要<｜｜DSML｜｜ calls>query_metrics")])

    out = await summarize_early_context(
        messages, results, llm=llm, budget=_budget(), locale=ZH, remaining_calls=1
    )

    assert out.strategy_used is CompactionStrategy.TOOL_RESULT_PRUNING
    assert out.llm_calls == 1
    assert all("DSML" not in m.content for m in out.messages)


async def test_budget_error_after_charging_counts_the_charged_call() -> None:
    """台账：调用次数先扣后发；预算异常时按实际扣减计数，不一律记 0。"""

    from app.llm.client import LlmBudgetExceededError

    class ChargedThenRefused(FakeLlmClient):
        async def converse(self, *, budget: LlmBudget, **kwargs: object) -> LlmTurn:  # type: ignore[override]
            budget.charge_call()
            raise LlmBudgetExceededError("token 上限")

    messages, results = _conversation(4)
    out = await summarize_early_context(
        messages, results, llm=ChargedThenRefused(turns=[]), budget=_budget(), locale=ZH,
        remaining_calls=1,
    )
    assert out.strategy_used is CompactionStrategy.TOOL_RESULT_PRUNING
    assert out.llm_calls == 1
