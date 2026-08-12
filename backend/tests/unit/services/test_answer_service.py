from __future__ import annotations

from decimal import Decimal

import pytest

from app.llm.client import LlmBudget
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricPayload
from app.repositories.analytics import ResultColumn
from app.services.safe_query import QueryResult


def _facts():
    from app.services.answer_service import AnswerFacts

    return AnswerFacts(
        question="最近一天 GMV 是多少？",
        metric=MetricPayload(
            metric_code="gmv",
            display_name="成交 GMV",
            unit="元",
            definition="已付款订单金额之和",
            source="Borough 指标目录",
            owner="经营分析组",
            status="ACTIVE",
            generated=False,
            notice=None,
        ),
        query_result=QueryResult(
            columns=(ResultColumn("gmv", "成交 GMV", "METRIC"),),
            rows=[{"gmv": Decimal("12.00")}],
            total_rows=1,
            truncated=False,
            source_tables=("orders",),
            plan_steps=("按最近一天汇总成交 GMV",),
            export_spec=None,
            notes=(),
            non_additive=False,
        ),
    )


def _non_additive_facts():
    from app.services.answer_service import AnswerFacts

    return AnswerFacts(
        question="最近三天退货率分别是多少？",
        metric=MetricPayload(
            metric_code="return_rate",
            display_name="退货率",
            unit="%",
            definition="退货件数占发货件数的比例，按区间整体重算，不可加和",
            source="Borough 指标目录",
            owner="经营分析组",
            status="ACTIVE",
            generated=False,
            notice=None,
        ),
        query_result=QueryResult(
            columns=(
                ResultColumn("date", "日期", "DIMENSION"),
                ResultColumn("return_rate", "退货率", "METRIC"),
            ),
            rows=[
                {"date": "2026-08-01", "return_rate": Decimal("1.20")},
                {"date": "2026-08-02", "return_rate": Decimal("1.50")},
                {"date": "2026-08-03", "return_rate": Decimal("1.10")},
            ],
            total_rows=3,
            truncated=False,
            source_tables=("returns",),
            plan_steps=("按天汇总退货率",),
            export_spec=None,
            notes=(),
            non_additive=True,
        ),
    )


def _model_draft() -> str:
    return """{
      "answer": "最近一天成交 GMV 为 12.00 元。",
      "recommendations": [
        {
          "title": "关注成交表现",
          "evidence": "最近一天成交 GMV 为 12.00 元。",
          "action": "结合流量和转化继续观察。"
        },
        {
          "title": "核对查询范围",
          "evidence": "本次结果包含 1 行数据。",
          "action": "确认日期范围是否符合预期。"
        }
      ]
    }"""


@pytest.mark.asyncio
async def test_compose_uses_a_validated_model_draft() -> None:
    from app.services.answer_service import AnswerService

    result = await AnswerService().compose(
        _facts(),
        FakeLlmClient(responses=[_model_draft()]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is False
    assert result.draft.answer == "最近一天成交 GMV 为 12.00 元。"
    assert len(result.draft.recommendations) == 2


@pytest.mark.asyncio
async def test_compose_degrades_to_a_factual_draft_for_invalid_json() -> None:
    from app.services.answer_service import AnswerService

    result = await AnswerService().compose(
        _facts(),
        FakeLlmClient(behaviour="invalid_json"),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is True
    assert "12.00" in result.draft.answer
    assert len(result.draft.recommendations) == 2
    assert result.notes == ["回答生成已降级为受控数据摘要。"]


@pytest.mark.asyncio
async def test_compose_rejects_a_draft_that_sums_a_non_additive_metric() -> None:
    from app.services.answer_service import AnswerService

    draft = """{
      "answer": "最近三天退货率合计 3.80%。",
      "recommendations": [
        {"title": "关注退货率", "evidence": "1.20", "action": "结合物流排查原因。"},
        {"title": "核对区间", "evidence": "1.50", "action": "确认口径是否符合预期。"}
      ]
    }"""
    result = await AnswerService().compose(
        _non_additive_facts(),
        FakeLlmClient(responses=[draft]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is True


@pytest.mark.asyncio
async def test_compose_rejects_a_draft_that_leaks_an_internal_identifier() -> None:
    from app.services.answer_service import AnswerService

    draft = """{
      "answer": "本次查询由 1c3b8a2e-4f5d-4a11-9c2a-7d6e5f4b3a21 执行，GMV 为 12.00 元。",
      "recommendations": [
        {"title": "关注成交表现", "evidence": "GMV 为 12.00 元。", "action": "结合流量继续观察。"},
        {"title": "核对查询范围", "evidence": "本次结果包含 1 行数据。", "action": "确认日期范围。"}
      ]
    }"""
    result = await AnswerService().compose(
        _facts(),
        FakeLlmClient(responses=[draft]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is True


def test_facts_json_reports_the_non_additive_flag() -> None:
    from app.services.answer_service import AnswerService

    additive = AnswerService().facts_json(_facts())
    non_additive = AnswerService().facts_json(_non_additive_facts())

    assert '"non_additive":false' in additive
    assert '"non_additive":true' in non_additive


@pytest.mark.asyncio
async def test_compose_rejects_a_draft_with_a_number_missing_from_query_result() -> None:
    from app.services.answer_service import AnswerService

    invalid_number = _model_draft().replace("12.00", "99.00")
    result = await AnswerService().compose(
        _facts(),
        FakeLlmClient(responses=[invalid_number]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is True
    assert "12.00" in result.draft.answer
