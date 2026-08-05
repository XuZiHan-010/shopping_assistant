"""query_data 节点接入真实查询后的行为。

用假的查询服务：图这一层要验证的是「拿到结果怎么填响应」，SQL 正确性由
tests/integration 的仓储测试负责。
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.graph import MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.repositories.analytics import ResultColumn
from app.schemas.chat import AnalysisSource, AnswerMode, QualityStatus
from app.services.safe_query import QueryResult, UnsupportedQueryError


class _Documents:
    async def list_active(self) -> list[object]:
        return []


class _NoMetric:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _StubQueryService:
    def __init__(self, result: QueryResult | Exception) -> None:
        self._result = result
        self.calls = 0

    async def execute(self, context: object, intent: object, *, now: object) -> QueryResult:
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _metric_result() -> QueryResult:
    return QueryResult(
        columns=(
            ResultColumn("date", "日期", "DIMENSION"),
            ResultColumn("gmv", "成交 GMV", "METRIC"),
        ),
        rows=[{"date": date(2026, 8, 3), "gmv": Decimal("1200.00")}],
        total_rows=1,
        truncated=False,
        source_tables=("orders",),
        plan_steps=("按商家范围检索成交 GMV",),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


def _llm() -> FakeLlmClient:
    return FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": "TRADE",
                    "metric": "gmv",
                    "dimensions": ["date"],
                    "filters": {},
                    "date_range": {"start": "2026-08-03", "end": "2026-08-03"},
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )


def _graph(service: _StubQueryService) -> MerchantQaGraph:
    llm = _llm()
    return MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
        query_service=service,
        merchant_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_metric_answer_carries_real_rows_and_drops_the_b4_fallback() -> None:
    service = _StubQueryService(_metric_result())

    result = await _graph(service).run("昨天 GMV", uuid4())

    assert service.calls == 1
    assert result.response.data_rows == [{"date": "2026-08-03", "gmv": "1200.00"}]
    assert result.response.total_rows == 1
    assert result.response.analysis_sources == [AnalysisSource.DATABASE]
    assert result.response.degraded is False


@pytest.mark.asyncio
async def test_query_plan_summary_comes_from_the_query_not_a_placeholder() -> None:
    service = _StubQueryService(_metric_result())

    result = await _graph(service).run("昨天 GMV", uuid4())

    assert result.response.query_plan is not None
    assert "成交 GMV" in result.response.query_plan.summary


@pytest.mark.asyncio
async def test_refused_query_degrades_visibly_instead_of_faking_data() -> None:
    """查询被拒时绝不能返回空数组假装「没有数据」。"""

    service = _StubQueryService(UnsupportedQueryError("指标 seller_secret 不在可查询范围内"))

    result = await _graph(service).run("查个不存在的指标", uuid4())

    assert result.response.degraded is True
    assert "不在可查询范围内" in (result.response.degraded_reason or "")
    assert result.response.analysis_sources == [AnalysisSource.FALLBACK]
    assert result.response.quality_status is QualityStatus.DEGRADED


@pytest.mark.asyncio
async def test_no_query_service_keeps_the_previous_degradation_path() -> None:
    """未注入查询服务（例如单测环境）时，行为退回 B3 的可见降级，而不是崩溃。"""

    llm = _llm()
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
    )

    result = await graph.run("昨天 GMV", uuid4())

    assert result.response.answer_mode is AnswerMode.METRIC
    assert result.response.degraded is True
