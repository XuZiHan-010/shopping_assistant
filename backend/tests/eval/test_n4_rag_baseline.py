"""E5 RAG 关键词基线（N4-C Task 1）：评测集结构、指标计算与基线评估管线。

只测确定性部分（Recall@k、MRR、nDCG@5、找不到时的承认率）；引用正确率与回答忠实度需要
LLM 裁判（R3），不在这里。
"""

from __future__ import annotations

import math
from collections import Counter

import pytest

from app.eval.rag_e5 import (
    evaluate,
    load_rag_cases,
    ndcg_at_k,
    platform_domain_retriever,
    recall_at_k,
    reciprocal_rank,
)
from app.knowledge.wiki_seed import load_wiki_seed_entries

KINDS = {"caliber", "process", "field", "colloquial", "cross_language", "multi_doc", "no_answer"}


def test_dataset_is_large_enough_and_labels_real_documents() -> None:
    cases = load_rag_cases()
    corpus = {entry.source_path for entry in load_wiki_seed_entries()}

    assert len(cases) >= 60
    assert len({case["id"] for case in cases}) == len(cases)
    kinds = Counter(case["kind"] for case in cases)
    assert set(kinds) == KINDS
    assert kinds["no_answer"] >= 8 and kinds["cross_language"] >= 8
    for case in cases:
        assert set(case["expected"]) <= corpus, case["id"]
        assert (case["kind"] == "no_answer") == (case["expected"] == []), case["id"]


def test_recall_counts_expected_documents_within_k() -> None:
    assert recall_at_k(["a", "b", "c"], ["c", "x"], k=3) == 0.5
    assert recall_at_k(["a", "b", "c"], ["c"], k=2) == 0.0
    assert recall_at_k([], ["a"], k=5) == 0.0


def test_reciprocal_rank_uses_first_relevant_position() -> None:
    assert reciprocal_rank(["x", "a", "b"], ["a", "b"]) == 0.5
    assert reciprocal_rank(["x", "y"], ["a"]) == 0.0


def test_ndcg_rewards_relevant_documents_ranked_early() -> None:
    assert ndcg_at_k(["a", "b"], ["a", "b"], k=5) == pytest.approx(1.0)
    swapped = ndcg_at_k(["x", "a"], ["a"], k=5)
    assert swapped == pytest.approx(1 / math.log2(3))
    assert ndcg_at_k(["x"], ["a"], k=5) == 0.0


@pytest.mark.asyncio
async def test_baseline_retriever_reproduces_the_old_search_rules_path() -> None:
    """基线复现 N3 `search_rules` 原路径：tokenize → 平台规则域 load_domain。"""

    ranked, matched = await platform_domain_retriever("平台规则是怎么发布和执行的")

    assert matched is True
    assert "业务/平台规则/业务流程/平台规则业务流程图.md" in ranked


@pytest.mark.asyncio
async def test_baseline_report_has_all_metrics_and_no_query_text() -> None:
    cases = load_rag_cases()

    report = await evaluate(cases, platform_domain_retriever)

    overall = report["overall"]
    for key in ("recall_at_3", "recall_at_5", "mrr", "ndcg_at_5"):
        assert 0.0 <= overall[key] <= 1.0
    assert report["answerable_cases"] + report["no_answer_cases"] == len(cases)
    assert 0.0 <= report["no_answer_rejection_rate"] <= 1.0
    assert set(report["by_kind"]) == KINDS - {"no_answer"}
    assert report["pending"] == ["citation_accuracy", "faithfulness"]
    text = repr(report)
    assert all(case["query"] not in text for case in cases)


@pytest.mark.asyncio
async def test_oracle_domain_diagnostic_isolates_domain_filter_loss() -> None:
    """诊断对照只换业务域、不换匹配方式：它的召回不应低于生产路径。"""

    from app.eval.rag_e5 import oracle_domain_retriever_for

    cases = load_rag_cases()
    production = await evaluate(cases, platform_domain_retriever)
    oracle = await evaluate(cases, oracle_domain_retriever_for(cases))

    assert oracle["retriever"] == "oracle_domain_retriever"
    assert oracle["overall"]["recall_at_5"] >= production["overall"]["recall_at_5"]


@pytest.mark.asyncio
async def test_search_rules_beats_the_platform_domain_baseline() -> None:
    """改为全文档检索后，召回、排序与拒答三项都不得劣于原路径（计划 Task 4 步骤 3 的上线条件）。"""

    from app.eval.rag_e5 import search_rules_retriever

    cases = load_rag_cases()
    baseline = await evaluate(cases, platform_domain_retriever)
    current = await evaluate(cases, search_rules_retriever)

    assert current["overall"]["recall_at_5"] > baseline["overall"]["recall_at_5"]
    assert current["overall"]["mrr"] > baseline["overall"]["mrr"]
    assert current["no_answer_rejection_rate"] >= baseline["no_answer_rejection_rate"]
