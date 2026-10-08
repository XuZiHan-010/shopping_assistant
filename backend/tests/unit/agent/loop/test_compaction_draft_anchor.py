"""复审 F7：草稿版本锚点在两种压缩策略下端到端保留（N4-3①，D9「批准绑定草案版本」）。

此前只在抽取/格式化层测过草稿锚点；这里把一轮起草补货放进被压缩的早期轮次，
分别走工具结果清理与摘要（Fake 摘要故意什么都不保留），断言草稿编号与版本仍在上下文里。
"""

from __future__ import annotations

from dataclasses import replace

from app.agent.loop.compaction.pruning import prune_tool_results
from app.agent.loop.compaction.summarization import summarize_early_context
from app.llm.client import LlmBudget, LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale
from app.tools.types import ToolOutcome

from .test_compaction_anchors import _draft
from .test_compaction_pruning import _conversation

ZH = SupportedLocale.ZH_CN


def _with_early_draft():  # type: ignore[no-untyped-def]
    messages, results = _conversation(4)
    first_call = next(i for i, m in enumerate(messages) if m.tool_calls)
    messages[first_call] = replace(
        messages[first_call],
        tool_calls=[LlmToolCall(call_id="c1", tool_name="draft_restock", arguments_json="{}")],
    )
    draft = _draft("draft-42")
    results[0] = replace(draft, display=replace(draft.display, call_id="c1"))
    assert results[0].outcome is ToolOutcome.DRAFT_CREATED
    return messages, results


def _context(messages) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(m.content for m in messages)


def test_pruning_keeps_draft_id_and_version() -> None:
    messages, results = _with_early_draft()
    out = prune_tool_results(messages, results, locale=ZH, keep_recent_rounds=2)
    assert out.changed is True
    text = _context(out.messages)
    assert "draft-42" in text and "版本" in text and "1" in text


async def test_summarization_keeps_draft_id_and_version_even_if_summary_drops_it() -> None:
    messages, results = _with_early_draft()
    llm = FakeLlmClient(
        turns=[LlmTurn(text="早期对话。", tool_calls=[], stop_reason="END_TURN", tokens=10)]
    )
    out = await summarize_early_context(
        messages, results, llm=llm, budget=LlmBudget(max_calls=4, max_tokens=100_000),
        locale=ZH, remaining_calls=1,
    )
    assert out.changed is True and out.llm_calls == 1
    assert "draft-42" in out.messages[1].content
