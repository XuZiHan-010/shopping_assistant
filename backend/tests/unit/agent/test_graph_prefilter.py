"""零 LLM 前置闸门接入图后的端到端行为。

对应 openspec/changes/add-question-prefilter-gate/specs/chat/question-prefilter/spec.md。
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from app.agent.graph import GRAPH_NODES, MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.schemas.chat import AnalysisSource, AnswerMode, QualityStatus


class D:
    def __init__(self, p: str, title: str, c: str) -> None:
        self.source_path = p
        self.title = title
        self.content = c
        self.is_complete = True


class K:
    def __init__(self, documents: list[D] | None = None) -> None:
        self._documents = documents or [D("index/README.md", "退款退货域", "退货 退款 售后")]

    async def list_active(self) -> list[D]:
        return self._documents


class M:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _NoHistory:
    async def has_assistant_message(self, merchant_id: UUID, conversation_id: UUID) -> bool:
        del merchant_id, conversation_id
        return False


class _HasHistory:
    async def has_assistant_message(self, merchant_id: UUID, conversation_id: UUID) -> bool:
        del merchant_id, conversation_id
        return True


def _metric_intent_response() -> str:
    return json.dumps(
        {
            "answer_mode": "METRIC",
            "category": "TRADE",
            "metric": "gmv",
            "dimensions": [],
            "filters": {},
            "date_range": None,
            "sort": None,
            "limit": None,
            "followup_reference": False,
            "needs_attachment": False,
        }
    )


def test_graph_nodes_include_prefilter_between_index_and_classify() -> None:
    assert len(GRAPH_NODES) == 12
    assert GRAPH_NODES.index("prefilter_question") == GRAPH_NODES.index(
        "retrieve_knowledge_index"
    ) + 1
    assert GRAPH_NODES.index("prefilter_question") == GRAPH_NODES.index("classify_intent") - 1


@pytest.mark.asyncio
async def test_offtopic_question_rejected_with_zero_llm_calls() -> None:
    llm = FakeLlmClient(responses=[])
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        prefilter_enabled=True,
        prefilter_min_score=3,
        session_history=_NoHistory(),
        merchant_id=uuid4(),
    )

    result = await graph.run("CNN 和 RNN 的区别是什么", uuid4())

    assert llm.calls == []
    assert result.response.answer_mode is AnswerMode.INVALID
    assert result.response.degraded is False
    assert result.response.degraded_reason is None
    assert result.response.quality_status is QualityStatus.NOT_RUN
    assert result.response.analysis_sources == [AnalysisSource.NONE]
    assert result.response.suggestions


@pytest.mark.asyncio
async def test_offtopic_question_skips_llm_driven_nodes() -> None:
    llm = FakeLlmClient(responses=[])
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        prefilter_enabled=True,
        session_history=_NoHistory(),
        merchant_id=uuid4(),
    )

    result = await graph.run("CNN 和 RNN 的区别是什么", uuid4())

    assert [step.node for step in result.steps] == [
        "load_context",
        "retrieve_knowledge_index",
        "prefilter_question",
        "suggest_questions",
        "persist_answer",
    ]


@pytest.mark.asyncio
async def test_business_question_still_reaches_llm_and_all_nodes_run() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["退货量"]}
            ),
            _metric_intent_response(),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        prefilter_enabled=True,
        session_history=_NoHistory(),
        merchant_id=uuid4(),
    )

    result = await graph.run("最近 7 天退货量趋势", uuid4())

    assert len(llm.calls) > 0
    assert [step.node for step in result.steps] == list(GRAPH_NODES)


@pytest.mark.asyncio
async def test_session_with_prior_turn_bypasses_gate_even_without_business_terms() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "CHAT", "category": "UNKNOWN", "intent_keywords": []})
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        prefilter_enabled=True,
        session_history=_HasHistory(),
        merchant_id=uuid4(),
    )

    result = await graph.run("CNN 和 RNN 的区别是什么", uuid4())

    assert len(llm.calls) > 0
    assert result.response.answer_mode is not AnswerMode.INVALID


@pytest.mark.asyncio
async def test_prefilter_disabled_by_default_matches_pre_existing_behavior() -> None:
    """默认构造（不传 prefilter_enabled）必须与引入本能力之前的行为完全一致——
    既有单测大量以这种方式构造 `MerchantQaGraph`，不得因为新增闸门而全部改写。"""

    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}
            ),
            _metric_intent_response(),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("昨天GMV", uuid4())

    assert result.response.answer_mode is AnswerMode.METRIC
    assert [step.node for step in result.steps] == list(GRAPH_NODES)
