from __future__ import annotations

import json
from datetime import date

import pytest

from app.intent.service import MAX_INTENT_RETRIES, IntentService
from app.llm.client import LlmBudget
from app.llm.fake import FakeLlmClient
from app.schemas.chat import AnswerMode, QuestionCategory


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=10, max_tokens=10_000)


def _classify(mode: str = "METRIC", category: str = "TRADE") -> str:
    return json.dumps({"answer_mode": mode, "category": category, "intent_keywords": ["GMV"]})


def _understand(**changes: object) -> str:
    value: dict[str, object] = {
        "answer_mode": "METRIC",
        "category": "TRADE",
        "metric": "gmv",
        "dimensions": [],
        "filters": {},
        "date_range": {"start": "2026-08-01", "end": "2026-08-03"},
        "sort": None,
        "limit": None,
        "followup_reference": False,
        "needs_attachment": False,
    }
    value.update(changes)
    return json.dumps(value)


@pytest.mark.asyncio
async def test_recognize_uses_index_and_returns_initial_intent() -> None:
    llm = FakeLlmClient(responses=[_classify()])
    initial = await IntentService(llm).recognize("昨天 GMV", "索引文本", _budget())
    assert initial.answer_mode is AnswerMode.METRIC
    assert initial.category is QuestionCategory.TRADE
    assert "索引文本" in llm.calls[0][1]


@pytest.mark.asyncio
async def test_understand_validates_structured_intent() -> None:
    service = IntentService(FakeLlmClient(responses=[_classify(), _understand()]))
    initial = await service.recognize("昨天 GMV", "索引", _budget())
    outcome = await service.understand("昨天 GMV", initial, "正文", _budget(), date(2026, 8, 4))
    assert outcome.intent.metric == "gmv"
    assert outcome.degraded is False


@pytest.mark.asyncio
async def test_invalid_json_retries_then_degrades() -> None:
    llm = FakeLlmClient(responses=[_classify(), "不是 JSON", "不是 JSON", "不是 JSON"])
    service = IntentService(llm)
    initial = await service.recognize("你好", "索引", _budget())
    start = len(llm.calls)
    outcome = await service.understand("你好", initial, "正文", _budget(), date(2026, 8, 4))
    assert outcome.intent.answer_mode is AnswerMode.CHAT
    assert outcome.degraded is True
    assert len(llm.calls) - start == MAX_INTENT_RETRIES + 1


@pytest.mark.asyncio
async def test_unconfigured_llm_degrades_without_repeated_understand_attempts() -> None:
    llm = FakeLlmClient(configured=False)
    service = IntentService(llm)
    initial = await service.recognize("你好", "索引", _budget())
    outcome = await service.understand("你好", initial, "正文", _budget(), date(2026, 8, 4))

    assert outcome.degraded is True
    assert "未配置" in (outcome.degraded_reason or "")
    assert outcome.notes == ("LLM 未配置或暂不可用，已返回可见降级结果。",)
    assert llm.calls == []


@pytest.mark.asyncio
async def test_sql_metric_becomes_invalid() -> None:
    service = IntentService(
        FakeLlmClient(responses=[_classify(), _understand(metric="SELECT 1 FROM orders")])
    )
    initial = await service.recognize("问题", "索引", _budget())
    outcome = await service.understand("问题", initial, "正文", _budget(), date(2026, 8, 4))
    assert outcome.intent.answer_mode is AnswerMode.INVALID
