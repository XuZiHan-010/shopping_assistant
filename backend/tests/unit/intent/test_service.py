from __future__ import annotations

import json
from datetime import date

import pytest

from app.intent.prompts import understand_user_prompt
from app.intent.service import MAX_INTENT_RETRIES, IntentService
from app.llm.client import STRUCTURED_CALL_OPTIONS, LlmBudget
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


def test_understand_prompt_constrains_generated_metric_plan_to_fixed_templates() -> None:
    prompt = understand_user_prompt(
        "按 SPU 看成交表现", "TRADE", "交易知识", today=date(2026, 8, 17)
    )

    assert "generated_metric_plan" in prompt
    assert "spu_id" in prompt
    assert "address_city_name" in prompt
    assert "TRADE" in prompt
    assert "REFUND" in prompt
    assert "自由公式" in prompt
    assert "表名" in prompt


@pytest.mark.asyncio
async def test_recognize_uses_index_and_returns_initial_intent() -> None:
    llm = FakeLlmClient(responses=[_classify()])
    initial = await IntentService(llm).recognize("昨天 GMV", "索引文本", _budget())
    assert initial.answer_mode is AnswerMode.METRIC
    assert initial.category is QuestionCategory.TRADE
    assert "索引文本" in llm.calls[0][1]
    assert llm.call_options == [STRUCTURED_CALL_OPTIONS]


@pytest.mark.asyncio
async def test_recognize_retries_legal_but_useless_unknown_for_business_question() -> None:
    """业务问题不应因模型给出合法的 INVALID/UNKNOWN 而直接短路。"""

    llm = FakeLlmClient(responses=[_classify("INVALID", "UNKNOWN"), _classify()])

    initial = await IntentService(llm).recognize("最近七天成交额趋势如何？", "业务索引", _budget())

    assert initial.answer_mode is AnswerMode.METRIC
    assert initial.category is QuestionCategory.TRADE
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_recognize_retries_chat_unknown_for_business_question() -> None:
    """业务问题被误判为 CHAT/UNKNOWN 时也不能跳过第二次分类。"""

    llm = FakeLlmClient(responses=[_classify("CHAT", "UNKNOWN"), _classify()])

    initial = await IntentService(llm).recognize("最近七天成交额趋势如何？", "业务索引", _budget())

    assert initial.answer_mode is AnswerMode.METRIC
    assert initial.category is QuestionCategory.TRADE
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_recognize_retries_business_domain_answered_as_chat() -> None:
    """业务域已判定却把 answer_mode 退成 CHAT，是自相矛盾的输出，必须重分类。

    2026-08-26 真实 `deepseek-v4-flash` 实测：「商品上架需要满足什么条件」返回
    `category=PLATFORM_RULE` + `answer_mode=CHAT`。此时知识库正文其实已经检索到，
    却因为走了 CHAT 分支被整段丢弃，用户只拿到「已完成结构化理解。」，且
    `degraded=false` 不给任何提示。
    """

    llm = FakeLlmClient(
        responses=[_classify("CHAT", "PLATFORM_RULE"), _classify("RULE", "PLATFORM_RULE")]
    )

    initial = await IntentService(llm).recognize("商品上架需要满足什么条件", "业务索引", _budget())

    assert initial.answer_mode is AnswerMode.RULE
    assert initial.category is QuestionCategory.PLATFORM_RULE
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_recognize_keeps_chat_when_category_is_unknown_and_not_business() -> None:
    """真正的闲聊（CHAT + UNKNOWN）不得被这条新规则误伤成多花一次调用。"""

    llm = FakeLlmClient(responses=[_classify("CHAT", "UNKNOWN")])

    initial = await IntentService(llm).recognize("你好", "业务索引", _budget())

    assert initial.answer_mode is AnswerMode.CHAT
    assert initial.category is QuestionCategory.UNKNOWN
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_recognize_retries_business_domain_chat_only_once() -> None:
    """模型两次都给自相矛盾结果时必须收敛，不能无限重试。"""

    llm = FakeLlmClient(
        responses=[_classify("CHAT", "PLATFORM_RULE"), _classify("CHAT", "PLATFORM_RULE")]
    )

    initial = await IntentService(llm).recognize("商品上架需要满足什么条件", "业务索引", _budget())

    assert len(llm.calls) == 2
    assert initial.llm_analyzed is True


@pytest.mark.asyncio
async def test_understand_validates_structured_intent() -> None:
    llm = FakeLlmClient(responses=[_classify(), _understand()])
    service = IntentService(llm)
    initial = await service.recognize("昨天 GMV", "索引", _budget())
    outcome = await service.understand("昨天 GMV", initial, "正文", _budget(), date(2026, 8, 4))
    assert outcome.intent.metric == "gmv"
    assert outcome.degraded is False
    assert llm.call_options == [STRUCTURED_CALL_OPTIONS, STRUCTURED_CALL_OPTIONS]


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
async def test_empty_structured_content_retries_then_degrades() -> None:
    """成功响应的空正文仍按无效 JSON 处理，不得产生伪造意图。"""

    llm = FakeLlmClient(responses=[_classify(), "", "", ""])
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
