from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.agent.graph import GRAPH_NODES, MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.schemas.chat import AnalysisSource, AnswerMode, QualityStatus


class D:
    def __init__(self, p: str, c: str) -> None:
        self.source_path = p
        self.title = p
        self.content = c
        self.is_complete = True


class K:
    def __init__(self, documents: list[D] | None = None) -> None:
        self._documents = documents or [
            D("index/README.md", "交易"),
            D("业务/交易/正文.md", "订单 GMV"),
        ]

    async def list_active(self) -> list[D]:
        return self._documents


class EmptyK:
    async def list_active(self) -> list[D]:
        return []


class M:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class Memory:
    def __init__(self, category: str, content: str) -> None:
        self.category = category
        self.content = content


class MemoryRepo:
    def __init__(self, memories: list[Memory]) -> None:
        self._memories = memories

    async def list_for_merchant(self, merchant_id, category: str) -> list[Memory]:
        del merchant_id
        return [memory for memory in self._memories if memory.category == category]


def response(mode: str, metric: str | None) -> str:
    return json.dumps(
        {
            "answer_mode": mode,
            "category": "TRADE" if mode == "METRIC" else "UNKNOWN",
            "metric": metric,
            "dimensions": [],
            "filters": {},
            "date_range": None,
            "sort": None,
            "limit": None,
            "followup_reference": False,
            "needs_attachment": False,
        }
    )


@pytest.mark.asyncio
async def test_graph_emits_all_nodes_and_routes_metric() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            response("METRIC", "gmv"),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )
    result = await graph.run("昨天GMV", uuid4())
    assert result.response.answer_mode is AnswerMode.METRIC
    assert [step.node for step in result.steps] == list(GRAPH_NODES)


def rule_response() -> str:
    return json.dumps(
        {
            "answer_mode": "RULE",
            "category": "PLATFORM_RULE",
            "metric": None,
            "dimensions": [],
            "filters": {},
            "date_range": None,
            "sort": None,
            "limit": None,
            "followup_reference": False,
            "needs_attachment": False,
        }
    )


@pytest.mark.asyncio
async def test_graph_rule_answer_uses_knowledge_content_and_source() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {
                    "answer_mode": "RULE",
                    "category": "PLATFORM_RULE",
                    "intent_keywords": ["上架"],
                }
            ),
            rule_response(),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K([D("rules/listing.md", "商品上架前必须完成资质审核。")])),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
    )

    result = await graph.run("商品上架有什么规则", uuid4())

    assert "商品上架前必须完成资质审核" in result.response.answer
    assert "rules/listing.md" in result.response.answer
    assert result.response.analysis_sources == [AnalysisSource.KNOWLEDGE]


@pytest.mark.asyncio
async def test_graph_rule_answer_surfaces_memory_not_team_knowledge() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {
                    "answer_mode": "RULE",
                    "category": "PLATFORM_RULE",
                    "intent_keywords": ["上架"],
                }
            ),
            rule_response(),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(
            EmptyK(),
            memories=MemoryRepo([Memory("PLATFORM_RULE", "历史规则记忆")]),
            merchant_id=uuid4(),
        ),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
    )

    result = await graph.run("商品上架有什么规则", uuid4())

    assert result.response.analysis_sources == [AnalysisSource.MEMORY]
    assert any("历史记忆" in note for note in result.response.quality_notes)


@pytest.mark.asyncio
async def test_graph_rule_answer_explicitly_reports_knowledge_miss() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {
                    "answer_mode": "RULE",
                    "category": "PLATFORM_RULE",
                    "intent_keywords": ["入库"],
                }
            ),
            rule_response(),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K([D("index/README.md", "交易目录")])),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
    )

    result = await graph.run("入库流程是什么", uuid4())

    assert "未命中" in result.response.answer
    assert any("未命中" in note for note in result.response.quality_notes)
    assert result.response.analysis_sources == [AnalysisSource.NONE]


@pytest.mark.asyncio
async def test_graph_marks_budget_exhaustion_as_visible_chat_degradation() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "CHAT", "category": "UNKNOWN", "intent_keywords": []})
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        max_llm_calls=1,
    )

    result = await graph.run("你好", uuid4())

    assert result.response.answer_mode is AnswerMode.CHAT
    assert result.response.degraded is True
    assert "调用次数或 token" in (result.response.degraded_reason or "")
    assert result.response.quality_status is QualityStatus.DEGRADED
    assert result.response.analysis_sources == [AnalysisSource.FALLBACK]


@pytest.mark.asyncio
async def test_graph_marks_unconfigured_llm_as_visible_chat_degradation() -> None:
    llm = FakeLlmClient(configured=False)
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("你好", uuid4())

    assert result.response.answer_mode is AnswerMode.CHAT
    assert result.response.degraded is True
    assert "未配置" in (result.response.degraded_reason or "")
    assert result.response.quality_status is QualityStatus.DEGRADED


@pytest.mark.asyncio
async def test_graph_routes_detail_to_visible_b4_degradation() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "DETAIL", "category": "TRADE", "intent_keywords": ["订单"]}),
            response("DETAIL", None),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("查看最近订单明细", uuid4())

    assert result.response.answer_mode is AnswerMode.DETAIL
    assert result.response.degraded is True
    assert result.response.data_rows == []
    assert result.response.export is not None


class _RecordingLlm:
    """记录每次调用的 user prompt，用来断言口径检索拿到的是哪一层知识。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def is_configured(self) -> bool:
        return True

    async def complete(self, *, system: str, user: str, fallback: str, budget: object) -> object:
        from app.llm.client import LlmResult

        self.prompts.append(user)
        return LlmResult(self._responses.pop(0) if self._responses else fallback, 10, False)


@pytest.mark.asyncio
async def test_generated_metric_definition_is_built_from_the_domain_body(monkeypatch) -> None:
    """索引层只有目录词汇；用它生成口径等于让模型凭空编。"""

    monkeypatch.setattr("app.metrics.catalog.find_field_comment", lambda _code: None)
    llm = _RecordingLlm(
        [
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            response("METRIC", "gmv"),
            json.dumps(
                {"display_name": "成交 GMV", "unit": "元", "definition": "已支付订单金额。"}
            ),
        ]
    )
    documents = [
        D("index/README.md", "交易 目录"),
        D("业务/交易/业务名词解释/GMV.md", "GMV 指已支付订单金额之和。"),
    ]
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K(documents)),
        intent_service_llm=llm,  # type: ignore[arg-type]
        catalog=MetricCatalog(M(), llm),  # type: ignore[arg-type]
    )

    await graph.run("昨天 GMV", uuid4())

    assert "GMV 指已支付订单金额之和。" in llm.prompts[-1]


@pytest.mark.asyncio
async def test_generated_metric_definition_carries_the_pending_review_notice(monkeypatch) -> None:
    """生成口径不标注待核验，用户会把模型猜的口径当成正式口径。"""

    monkeypatch.setattr("app.metrics.catalog.find_field_comment", lambda _code: None)
    from app.metrics.catalog import GENERATED_NOTICE

    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            response("METRIC", "gmv"),
            json.dumps(
                {"display_name": "成交 GMV", "unit": "元", "definition": "已支付订单金额。"}
            ),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("昨天 GMV", uuid4())

    assert result.response.metric_status.value == "UNVERIFIED"
    assert any(GENERATED_NOTICE in note for note in result.response.quality_notes)


@pytest.mark.asyncio
async def test_backend_date_clamp_is_reported_to_the_user() -> None:
    """后端悄悄改窄区间而不说明，用户会以为看到的是自己问的那段时间。"""

    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": "TRADE",
                    "metric": "gmv",
                    "dimensions": [],
                    "filters": {},
                    "date_range": {"start": "2020-01-01", "end": "2020-12-31"},
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("2020 年 GMV", uuid4())

    assert any("日期" in note for note in result.response.quality_notes)
