"""小结果原样保留、调用序号与知识文档出处（2026-10-10 整改，契约 §6.12）。

2026-10-07 真实评测的售后回合：售后详情只有一两千字，却在两次规则检索之后被清理成一句摘要，
模型拿不到事实、无法起草决定。清掉小结果省不下空间，所以只清理超过 `min_prunable_chars` 的结果。
"""

from __future__ import annotations

from app.agent.loop.compaction import CompactionPolicy, CompactionStrategy, min_prunable_chars
from app.agent.loop.compaction.anchors import extract_anchors, format_anchors
from app.agent.loop.compaction.pruning import PRUNED_MARKER, prune_tool_results
from app.agent.loop.compaction.summarization import summarize_early_context
from app.agent.loop.runner import ContextCompacted, LoopEvent, run_loop
from app.llm.client import LlmBudget, LlmMessage, LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale
from app.schemas.v2.common import ToolDisplayStatus
from app.tools.types import ToolDisplay, ToolOutcome, ToolResult

from .loop_doubles import build_gates, call, end_turn, limits, merchant_request, tool_use_turn

ZH = SupportedLocale.ZH_CN
EN = SupportedLocale.EN_US
FLOOR = 500
DETAIL = '{"after_sale_type": "RETURN_REFUND", "reason": "商品与描述不符", "refund_cents": 39900}'
RULES = "条" * 3_000


def _result(tool: str, call_id: str, payload: object, summary: str = "已完成") -> ToolResult:
    return ToolResult(
        ok=True,
        payload=payload,
        display=ToolDisplay(
            tool_name=tool,
            call_id=call_id,
            status=ToolDisplayStatus.SUCCEEDED,
            duration_ms=1,
            row_count=1,
        ),
        reason_code=None,
        outcome=ToolOutcome.SUCCEEDED,
        summary=summary,
    )


def _after_sale_turn() -> tuple[list[LlmMessage], list[ToolResult]]:
    """队列 → 详情 → 两次规则检索 → 再一次检索：前两条很小，后三条很大。"""

    steps = [
        ("list_after_sales", '{"items": [{"after_sale_id": "as-1"}]}', {"items": []}),
        ("get_after_sale", DETAIL, {"reason": "商品与描述不符"}),
        ("search_rules", RULES, {"hits": [{"source_path": "业务/退货/a.md", "title": "规则甲"}]}),
        ("search_rules", RULES, {"hits": [{"source_path": "业务/退货/b.md", "title": "规则乙"}]}),
        ("search_rules", RULES, {"hits": []}),
    ]
    messages = [
        LlmMessage(role="system", content="你是 Borough 商家经营助手。"),
        LlmMessage(role="user", content="看看待处理的售后，帮我起草处理决定"),
    ]
    results: list[ToolResult] = []
    for index, (tool, content, payload) in enumerate(steps, 1):
        call_id = f"c{index}"
        messages.append(
            LlmMessage(
                role="assistant",
                content="",
                tool_calls=[LlmToolCall(call_id=call_id, tool_name=tool, arguments_json="{}")],
            )
        )
        messages.append(LlmMessage(role="tool", content=content, tool_call_id=call_id))
        results.append(_result(tool, call_id, payload))
    return messages, results


def _tool(messages: list[LlmMessage], call_id: str) -> str:
    return next(m.content for m in messages if m.tool_call_id == call_id)


def test_floor_is_a_quarter_of_the_trigger() -> None:
    policy = CompactionPolicy(
        strategy=CompactionStrategy.TOOL_RESULT_PRUNING, trigger_tokens=8_000, max_calls=1
    )

    assert policy.min_prunable_chars == min_prunable_chars(8_000) == 2_000


def test_small_results_survive_pruning_and_large_ones_do_not() -> None:
    messages, results = _after_sale_turn()

    out = prune_tool_results(
        messages, results, locale=ZH, keep_recent_rounds=2, min_prunable_chars=FLOOR
    )

    assert out.changed is True
    assert _tool(out.messages, "c1") == _tool(messages, "c1")
    assert _tool(out.messages, "c2") == DETAIL  # 售后详情原样保留
    assert RULES not in _tool(out.messages, "c3") and PRUNED_MARKER in _tool(out.messages, "c3")
    assert _tool(out.messages, "c4") == RULES and _tool(out.messages, "c5") == RULES  # 最近两轮


def test_nothing_changes_when_every_older_result_is_small() -> None:
    messages, results = _after_sale_turn()
    messages, results = messages[:-2], results[:-1]  # 只到第二次规则检索：较早的两条都很小

    out = prune_tool_results(
        messages, results, locale=ZH, keep_recent_rounds=2, min_prunable_chars=FLOOR
    )

    assert out.changed is False and out.messages == messages


def test_without_a_floor_every_older_result_is_pruned() -> None:
    messages, results = _after_sale_turn()

    out = prune_tool_results(messages, results, locale=ZH, keep_recent_rounds=2)

    assert all(PRUNED_MARKER in _tool(out.messages, c) for c in ("c1", "c2", "c3"))


def test_placeholder_states_the_call_ordinal_within_the_turn() -> None:
    messages, results = _after_sale_turn()

    zh = prune_tool_results(messages, results, locale=ZH, keep_recent_rounds=2)
    en = prune_tool_results(messages, results, locale=EN, keep_recent_rounds=2)

    assert "search_rules#c3，本回合第 3 次工具调用" in _tool(zh.messages, "c3")
    assert "list_after_sales#c1，本回合第 1 次工具调用" in _tool(zh.messages, "c1")
    assert "search_rules#c3; tool call 3 of this turn" in _tool(en.messages, "c3")


def test_pruned_rule_search_keeps_document_titles_and_citations() -> None:
    messages, results = _after_sale_turn()

    out = prune_tool_results(
        messages, results, locale=ZH, keep_recent_rounds=2, min_prunable_chars=FLOOR
    )

    pruned = _tool(out.messages, "c3")
    assert "规则甲" in pruned and "出处=业务/退货/a.md" in pruned


def test_document_anchors_take_only_title_and_citation() -> None:
    hits = [
        {"source_path": f"业务/退货/{n}.md", "title": f"规则{n}", "content": "正文不进锚点"}
        for n in range(7)
    ]
    policy = [{"title": "退货政策", "citation": "业务/平台规则/p.md", "excerpt": "摘录不进锚点"}]
    anchors = extract_anchors(
        [
            _result("search_rules", "c1", {"hits": hits, "merchant_id": "m-secret"}),
            _result("get_shop_policy", "c2", {"documents": policy}),
            _result("search_rules", "c3", {"hits": "不是列表"}),
        ]
    )

    text = format_anchors(anchors, ZH)

    assert [d.citation for d in anchors.documents[:5]] == [f"业务/退货/{n}.md" for n in range(5)]
    assert len([d for d in anchors.documents if d.ref == "search_rules#c1"]) == 5  # 每次最多 5 篇
    assert "退货政策 [get_shop_policy#c2]: 出处=业务/平台规则/p.md" in text
    assert "正文不进锚点" not in text and "摘录不进锚点" not in text and "m-secret" not in text


def test_anchor_heading_does_not_call_the_tool_a_source() -> None:
    """2026-10-06 真实评测：模型照着小标题「工具来源」把工具名写成了数据来源。"""

    metric = _result(
        "query_metrics",
        "c1",
        {
            "metric": "net_gmv",
            "value": "1000.00",
            "data_cutoff": "2026-09-28T16:00:00+00:00",
            "source": "DATABASE",
            "definition_version": "v2",
        },
    )

    zh = format_anchors(extract_anchors([metric]), ZH)
    en = format_anchors(extract_anchors([metric]), EN)

    assert "工具来源" not in zh and "已保留的调用记录:" in zh
    assert "Tool sources" not in en and "Retained calls:" in en
    row = next(line for line in zh.splitlines() if line.startswith("- query_metrics#c1"))
    for part in ("结果值=1000.00", "数据来源=DATABASE", "截至时间=2026-09-28", "定义版本=v2"):
        assert part in row  # 四项在同一行


async def test_summarization_keeps_rounds_whose_results_are_small() -> None:
    messages, results = _after_sale_turn()
    llm = FakeLlmClient(
        turns=[LlmTurn(text="商家要处理售后。", tool_calls=[], stop_reason="END_TURN", tokens=5)]
    )

    out = await summarize_early_context(
        messages,
        results,
        llm=llm,
        budget=LlmBudget(max_calls=2, max_tokens=100_000),
        locale=ZH,
        remaining_calls=1,
        keep_recent_rounds=2,
        min_prunable_chars=FLOOR,
    )

    assert out.strategy_used is CompactionStrategy.SUMMARIZATION and out.changed is True
    assert _tool(out.messages, "c2") == DETAIL  # 详情所在的轮整轮保留
    assert all(m.tool_call_id != "c3" for m in out.messages)  # 大结果所在的轮被吸收
    assert "规则甲" in out.messages[1].content  # 其文档出处随锚点回填


async def test_loop_keeps_the_after_sale_detail_through_compaction() -> None:
    """循环里的售后回合：详情之后两次大检索触发压缩，起草前模型仍看得到详情。"""

    events: list[LoopEvent] = []

    async def sink(event: LoopEvent) -> None:
        events.append(event)

    detail = call("slow_read", label="after-sale-detail")
    llm = FakeLlmClient(
        turns=[
            tool_use_turn(call("slow_read", label="queue")),
            tool_use_turn(detail),
            tool_use_turn(call("bulk_read", label="rules-1")),
            tool_use_turn(call("bulk_read", label="rules-2")),
            tool_use_turn(call("bulk_read", label="rules-3")),
            end_turn("已按规则起草，请在审批页确认。"),
        ]
    )
    gates = build_gates()[0]
    request = merchant_request("看看待处理的售后，帮我起草处理决定")
    policy = CompactionPolicy(
        strategy=CompactionStrategy.TOOL_RESULT_PRUNING, trigger_tokens=4_000, max_calls=1
    )

    out = await run_loop(
        request,
        llm=llm,
        gates=gates,
        tools=gates.registry.schemas_for(request.context.session.role),
        limits=limits(compaction=policy),
        on_event=sink,
    )

    assert out.stop_reason == "COMPLETED"
    # 第 5 次调用：较早的只有两条小结果，压缩没有可清理的内容，也不提示用户。
    fifth = llm.converse_calls[4].messages
    assert all(PRUNED_MARKER not in m.content for m in fifth)
    # 第 6 次调用：第一次大检索被清理，详情仍原样在上下文里。
    sixth = llm.converse_calls[5].messages
    assert "after-sale-detail" in _tool(sixth, detail.call_id)
    assert PRUNED_MARKER not in _tool(sixth, detail.call_id)
    assert sum(PRUNED_MARKER in m.content for m in sixth) == 1
    assert [type(e) for e in events if isinstance(e, ContextCompacted)] == [ContextCompacted]
