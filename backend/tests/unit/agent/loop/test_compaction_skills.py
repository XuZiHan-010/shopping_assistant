"""受信 Skill 不被压缩（审查 N4-3 I-2，PRD A4 / A5）。

`load_skill` 返回的受信 Skill 是做法说明，不是可清理的工具数据：
被清理成占位符后模型就看不到流程与约束，
重新加载又会占用单回合 `max_skill_loads`。两种策略都必须让它逐字保留，且消息结构仍合法。
"""

from __future__ import annotations

from app.agent.loop.compaction import CompactionStrategy, split_rounds
from app.agent.loop.compaction.pruning import prune_tool_results
from app.agent.loop.compaction.summarization import summarize_early_context
from app.llm.client import LlmBudget, LlmMessage, LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale
from app.schemas.v2.common import ToolDisplayStatus
from app.skills.spec import LOAD_SKILL_TOOL, SkillSpec, render_skill_message
from app.tools.types import ToolDisplay, ToolResult, ToolRole

from .test_compaction_pruning import _conversation

ZH = SupportedLocale.ZH_CN
SKILL = SkillSpec(
    name="pricing-promotions",
    version="1",
    roles=frozenset({ToolRole.MERCHANT}),
    body="起草优惠券前先确认折扣不低于 8 折；草稿交商家审批，不自行批准。",
    max_chars=8000,
    description="定价与促销",
    source="borough",
)


def _with_skill_first() -> tuple[list[LlmMessage], list[ToolResult]]:
    """[system, 历史…, 本轮 user, (skill 轮), (c1…c4 大结果轮)]"""

    messages, results = _conversation(4)
    prefix, rounds = split_rounds(messages)
    skill_call = LlmToolCall(call_id="s1", tool_name=LOAD_SKILL_TOOL, arguments_json="{}")
    skill_round = [
        LlmMessage(role="assistant", content="", tool_calls=[skill_call]),
        LlmMessage(role="tool", content=render_skill_message(SKILL), tool_call_id="s1"),
    ]
    skill_result = ToolResult(
        ok=True,
        payload=SKILL,
        display=ToolDisplay(LOAD_SKILL_TOOL, "s1", ToolDisplayStatus.SUCCEEDED, 1, None),
        reason_code=None,
    )
    flat = [*prefix, *skill_round, *(m for r in rounds for m in r)]
    return flat, [skill_result, *results]


def test_pruning_keeps_trusted_skill_verbatim() -> None:
    messages, results = _with_skill_first()

    out = prune_tool_results(messages, results, locale=ZH, keep_recent_rounds=1)

    assert out.changed is True
    assert render_skill_message(SKILL) in [m.content for m in out.messages]


async def test_summarization_keeps_trusted_skill_round_verbatim() -> None:
    messages, results = _with_skill_first()
    llm = FakeLlmClient(
        turns=[LlmTurn(text="早期对话。", tool_calls=[], stop_reason="END_TURN", tokens=1)]
    )

    out = await summarize_early_context(
        messages,
        results,
        llm=llm,
        budget=LlmBudget(max_calls=1, max_tokens=100_000),
        locale=ZH,
        remaining_calls=1,
        keep_recent_rounds=1,
    )

    assert out.strategy_used is CompactionStrategy.SUMMARIZATION
    assert render_skill_message(SKILL) in [m.content for m in out.messages]
    # 结构合法：每条 tool 消息都紧跟在声明了它的 assistant 之后。
    open_calls: set[str] = set()
    for message in out.messages:
        if message.role == "assistant" and message.tool_calls:
            open_calls = {c.call_id for c in message.tool_calls}
        elif message.role == "tool":
            assert message.tool_call_id in open_calls
    # Skill 正文不交给摘要模型转述。
    assert SKILL.body not in llm.converse_calls[0].messages[-1].content
