"""LangGraph 基线冻结守卫（Task 5，O4）。

这两条不是普通断言，是护栏：任何人改动被冻结的对象都会让它们失败，
逼着改动者在 `app/eval/baseline/FROZEN.md` 里解释为什么。
"""

from __future__ import annotations

from pathlib import Path

FROZEN_NODES = (
    "load_context",
    "retrieve_knowledge_index",
    "prefilter_question",
    "classify_intent",
    "understand_intent",
    "validate_intent",
    "retrieve_knowledge_detail",
    "query_data",
    "compose_answer",
    "quality_loop",
    "suggest_questions",
    "persist_answer",
)


def test_frozen_graph_nodes_unchanged() -> None:
    """O4：基线冻结。改动它就失去了对照参照。"""

    from app.agent.graph import GRAPH_NODES

    assert GRAPH_NODES == FROZEN_NODES


def test_baseline_not_wired_to_v2_routes() -> None:
    """基线不部署为新生产主流程。"""

    import app.agent.graph as graph_module

    src = Path(graph_module.__file__).read_text("utf-8")
    assert "/api/v2" not in src
