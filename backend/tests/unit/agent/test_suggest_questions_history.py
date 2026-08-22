"""猜你想问优先商家历史高频问题，异常时回落到静态推荐。"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest

from app.agent.graph import MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services.suggested_questions import suggestions_for

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000041")


class _Documents:
    async def list_active(self) -> list[object]:
        return []


class _NoMetric:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _StubHistory:
    def __init__(self, questions: list[str]) -> None:
        self._questions = questions
        self.calls: list[tuple[str, int]] = []

    async def top_category_questions(
        self, *, merchant_id: UUID, category: str, limit: int
    ) -> list[str]:
        self.calls.append((category, limit))
        return self._questions


class _RaisingHistory:
    async def top_category_questions(
        self, *, merchant_id: UUID, category: str, limit: int
    ) -> list[str]:
        raise RuntimeError("history unavailable")


def _llm() -> FakeLlmClient:
    return FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            json.dumps(
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
            ),
        ]
    )


def _graph(history_questions: _StubHistory | _RaisingHistory | None) -> MerchantQaGraph:
    llm = _llm()
    return MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
        merchant_id=MERCHANT_ID,
        history_questions=history_questions,
    )


@pytest.mark.asyncio
async def test_suggestions_prefer_merchant_history() -> None:
    """历史提供者有结果时只替换当前推荐，静态 alternates 仍可轮换。"""

    expected = ["高频问题一", "高频问题二", "高频问题三"]
    history = _StubHistory(expected)

    result = await _graph(history).run("昨天 GMV", uuid4())

    assert result.response.suggestions == expected
    assert history.calls == [("TRADE", 3)]
    assert result.response.suggestion_alternates


@pytest.mark.asyncio
async def test_suggestions_fall_back_to_presets_without_history() -> None:
    result = await _graph(_StubHistory([])).run("昨天 GMV", uuid4())

    expected = suggestions_for(QuestionCategory.TRADE, AnswerMode.METRIC)
    assert result.response.suggestions == expected.current
    assert result.response.suggestion_alternates == expected.alternates


@pytest.mark.asyncio
async def test_suggestions_fall_back_when_provider_absent() -> None:
    result = await _graph(None).run("昨天 GMV", uuid4())

    expected = suggestions_for(QuestionCategory.TRADE, AnswerMode.METRIC)
    assert result.response.suggestions == expected.current


@pytest.mark.asyncio
async def test_suggestions_fall_back_when_provider_raises() -> None:
    result = await _graph(_RaisingHistory()).run("昨天 GMV", uuid4())

    expected = suggestions_for(QuestionCategory.TRADE, AnswerMode.METRIC)
    assert result.response.suggestions == expected.current
