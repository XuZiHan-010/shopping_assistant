from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.graph import MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.repositories.analytics import ResultColumn
from app.schemas.chat import QualityStatus
from app.services.safe_query import QueryResult


class _Documents:
    async def list_active(self) -> list[object]:
        return []


class _MetricRepository:
    async def get_by_code(self, metric_code: str) -> object:
        return SimpleNamespace(
            metric_code="gmv",
            display_name="成交 GMV",
            unit="元",
            business_definition="已付款订单金额之和",
            source="Borough 指标目录",
            owner="经营分析组",
            status="ACTIVE",
        )


class _QueryService:
    async def execute(self, *args: object, **kwargs: object) -> QueryResult:
        return QueryResult(
            columns=(
                ResultColumn("date", "日期", "DIMENSION"),
                ResultColumn("gmv", "成交 GMV", "METRIC"),
            ),
            rows=[{"date": date(2026, 8, 5), "gmv": Decimal("12.00")}],
            total_rows=1,
            truncated=False,
            source_tables=("orders",),
            plan_steps=("按商家范围检索成交 GMV",),
            export_spec=None,
            notes=(),
            non_additive=False,
        )


def _intent_responses() -> list[str]:
    return [
        json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
        json.dumps(
            {
                "answer_mode": "METRIC",
                "category": "TRADE",
                "metric": "gmv",
                "dimensions": ["date"],
                "filters": {},
                "date_range": {"start": "2026-08-05", "end": "2026-08-05"},
                "sort": None,
                "limit": None,
                "followup_reference": False,
                "needs_attachment": False,
            }
        ),
    ]


def _draft() -> str:
    return json.dumps(
        {
            "answer": "2026-08-05 的成交 GMV 为 12.00 元。",
            "recommendations": [
                {"title": "关注成交", "evidence": "成交 GMV 为 12.00 元。", "action": "继续观察。"},
                {"title": "核对范围", "evidence": "结果包含 1 行数据。", "action": "确认日期。"},
            ],
        }
    )


@pytest.mark.asyncio
async def test_graph_retries_once_then_returns_passed_with_two_attempts() -> None:
    intent_llm = FakeLlmClient(responses=_intent_responses())
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=intent_llm,
        catalog=MetricCatalog(_MetricRepository(), intent_llm),
        query_service=_QueryService(),
        merchant_id=uuid4(),
        max_llm_calls=6,
        answer_llm=FakeLlmClient(responses=[_draft(), _draft()]),
        reviewer_llm=FakeLlmClient(
            responses=[
                '{"passed":false,"issues":["请补充核对"]}',
                '{"passed":true,"issues":[]}',
            ]
        ),
    )

    response = (await graph.run("最近一天 GMV", uuid4())).response

    assert response.quality_status is QualityStatus.PASSED
    assert response.quality_attempts == 2
    assert response.degraded is False
    assert response.visualization is not None and response.visualization.enabled is True
    assert len(response.recommendations or []) == 2


@pytest.mark.asyncio
async def test_graph_degrades_to_facts_after_two_reviewer_rejections() -> None:
    intent_llm = FakeLlmClient(responses=_intent_responses())
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=intent_llm,
        catalog=MetricCatalog(_MetricRepository(), intent_llm),
        query_service=_QueryService(),
        merchant_id=uuid4(),
        max_llm_calls=6,
        answer_llm=FakeLlmClient(responses=[_draft(), _draft()]),
        reviewer_llm=FakeLlmClient(
            responses=[
                '{"passed":false,"issues":["证据不足"]}',
                '{"passed":false,"issues":["仍需核对"]}',
            ]
        ),
    )

    response = (await graph.run("最近一天 GMV", uuid4())).response

    assert response.quality_status is QualityStatus.DEGRADED
    assert response.quality_attempts == 2
    assert response.degraded is True
    assert "12.00" in response.answer
