"""商家 Chat 的 `analysis_sources`：用过 `search_rules` 时如实标 KNOWLEDGE 与索引降级。

N4-C、§7.6、R7。
"""

from __future__ import annotations

from app.agent.loop.runner import LoopOutcome
from app.knowledge.index_versions import INDEX_FALLBACK_REASON, INDEX_STALE_REASON
from app.schemas.chat import QualityStatus
from app.schemas.v2.common import ToolDisplayStatus
from app.services.v2.merchant_chat import _sources
from app.tools.types import ToolDisplay, ToolResult


def _display(name: str, call_id: str) -> ToolDisplay:
    return ToolDisplay(
        tool_name=name,
        call_id=call_id,
        status=ToolDisplayStatus.SUCCEEDED,
        duration_ms=1,
        row_count=1,
    )


def _outcome(*calls: tuple[str, object, bool]) -> LoopOutcome:
    displays = [_display(name, f"c{i}") for i, (name, _payload, _ok) in enumerate(calls)]
    return LoopOutcome(
        answer="ok",
        tool_calls=displays,
        stop_reason="COMPLETED",
        degraded=False,
        degraded_reason=None,
        quality_status=QualityStatus.PASSED,
        quality_attempts=1,
        quality_notes=[],
        llm_calls=1,
        tool_results=[
            ToolResult(ok=ok, payload=payload, display=display, reason_code=None)
            for (_name, payload, ok), display in zip(calls, displays, strict=True)
        ],
    )


def _rule_payload(reason: str | None) -> dict[str, object]:
    return {"matched": True, "hits": [], "index_degraded_reason": reason}


def test_rule_answer_from_fresh_hybrid_index_is_undegraded_knowledge() -> None:
    sources = _sources(_outcome(("search_rules", _rule_payload(None), True)), used_tools=True)
    assert [(s.source, s.degraded, s.degraded_reason) for s in sources] == [
        ("KNOWLEDGE", False, None)
    ]


def test_keyword_fallback_marks_only_the_knowledge_source() -> None:
    outcome = _outcome(
        ("search_rules", _rule_payload(INDEX_FALLBACK_REASON), True),
        ("query_metrics", {}, True),
    )
    sources = _sources(outcome, used_tools=True)
    assert [(s.source, s.degraded, s.degraded_reason) for s in sources] == [
        ("KNOWLEDGE", True, INDEX_FALLBACK_REASON),
        ("DATABASE", False, None),
    ]
    assert outcome.degraded is False  # 单来源降级不等于整轮降级


def test_stale_index_is_visible() -> None:
    sources = _sources(
        _outcome(("search_rules", _rule_payload(INDEX_STALE_REASON), True)), used_tools=True
    )
    assert sources[0].degraded_reason == INDEX_STALE_REASON


def test_failed_rule_search_is_not_shown_as_clean_knowledge() -> None:
    sources = _sources(_outcome(("search_rules", None, False)), used_tools=True)
    assert sources[0].source == "KNOWLEDGE" and sources[0].degraded is True


def test_metric_only_turn_is_unchanged() -> None:
    sources = _sources(_outcome(("query_metrics", {}, True)), used_tools=True)
    assert [s.source for s in sources] == ["DATABASE"]
