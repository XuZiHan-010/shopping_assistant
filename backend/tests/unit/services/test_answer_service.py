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


def _trend_facts():
    """按日期维度返回多行的趋势事实包，复刻 2026-08-17 线上那一轮。"""

    from app.services.answer_service import AnswerFacts

    return AnswerFacts(
        question="最近7天的退货量趋势怎么样",
        metric=MetricPayload(
            metric_code="return_count",
            display_name="退货量",
            unit="件",
            definition="统计周期内发起退货的商品件数。",
            source="Borough 指标目录",
            owner="经营分析组",
            status="ACTIVE",
            generated=False,
            notice=None,
        ),
        query_result=QueryResult(
            columns=(
                ResultColumn("date", "日期", "DIMENSION"),
                ResultColumn("return_count", "退货量", "METRIC"),
            ),
            rows=[
                {"date": "2026-08-11", "return_count": 3},
                {"date": "2026-08-17", "return_count": 15},
            ],
            total_rows=2,
            truncated=False,
            source_tables=("returns",),
            plan_steps=("按日期汇总退货量",),
            export_spec=None,
            notes=(),
            non_additive=False,
        ),
    )


@pytest.mark.asyncio
async def test_compose_accepts_dates_written_in_chinese_form() -> None:
    """事实包用 ISO 日期，但中文回答里模型自然会写「8月11日」。

    2026-08-17 线上实测：一份完全基于事实的草稿因此被判成幻觉——`_validate` 只剥
    ISO 日期，剩下的 8/11/17 被当作「查询结果外的数字」，整轮回答降级成兜底摘要。
    日期成分是维度值，不是要与聚合结果逐项比对的业务数字，写成哪种格式都一样。
    """

    from app.services.answer_service import AnswerService

    draft = """{
      "answer": "8月11日退货量为 3 件，8月17日升至 15 件。",
      "recommendations": [
        {"title": "核查退货激增", "evidence": "8月17日退货量为 15 件。",
         "action": "调取当天退货明细。"},
        {"title": "持续观察", "evidence": "8月11日退货量为 3 件。",
         "action": "每日跟踪退货量。"}
      ]
    }"""

    result = await AnswerService().compose(
        _trend_facts(),
        FakeLlmClient(responses=[draft]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is False, "基于事实的中文日期草稿不应被判成幻觉"
    assert "8月11日" in result.draft.answer


@pytest.mark.asyncio
async def test_compose_still_rejects_business_numbers_outside_the_facts() -> None:
    """放行日期成分不能顺带放行编造的业务数字——这道守卫的本职必须保留。"""

    from app.services.answer_service import AnswerService

    draft = """{
      "answer": "8月11日退货量为 3 件，退款金额达到 98765 元。",
      "recommendations": [
        {"title": "核查退货", "evidence": "8月11日退货量为 3 件。", "action": "调取明细。"},
        {"title": "持续观察", "evidence": "8月17日退货量为 15 件。", "action": "每日跟踪。"}
      ]
    }"""

    result = await AnswerService().compose(
        _trend_facts(),
        FakeLlmClient(responses=[draft]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is True, "编造的 98765 必须仍被拦下"


@pytest.mark.asyncio
async def test_compose_accepts_the_time_window_restated_from_the_question() -> None:
    """模型复述用户问的时间窗口（「最近 7 天」）不是幻觉。

    2026-08-17 线上实测：日期写法修好后仍然降级，唯一越界数字是 7——来自
    「最近7天有记录的退货量中……」和「无法覆盖完整7天趋势」。时长表述与日期同类，
    都是时间成分，不是要与聚合结果逐项比对的业务数字。
    """

    from app.services.answer_service import AnswerService

    draft = """{
      "answer": "最近7天有记录的退货量中，8月11日为 3 件，8月17日达到 15 件。",
      "recommendations": [
        {"title": "核查退货激增", "evidence": "8月17日退货量为 15 件。",
         "action": "调取当天退货明细。"},
        {"title": "补齐监测", "evidence": "当前数据无法覆盖完整7天趋势。",
         "action": "确认拉取范围是否遗漏。"}
      ]
    }"""

    result = await AnswerService().compose(
        _trend_facts(),
        FakeLlmClient(responses=[draft]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is False, "复述问题里的时间窗口不应被判成幻觉"
    assert "最近7天" in result.draft.answer


@pytest.mark.asyncio
async def test_compose_accepts_dates_written_with_slashes() -> None:
    """模型也会把日期写成「8/12」「8/14-8/16」。

    2026-08-18 线上实测：4 次采样有 2 次因此降级，越界数字全是斜杠日期的成分。
    枚举格式是打地鼠，但数据里不存在的空档日期（8/14-8/16）只能靠剥格式覆盖。
    """

    from app.services.answer_service import AnswerService

    draft = """{
      "answer": "8/11、8/17 分别为 3 件和 15 件，期间 8/14-8/16 无记录。",
      "recommendations": [
        {"title": "核查激增", "evidence": "8/17 退货量为 15 件。",
         "action": "调取当天明细。"},
        {"title": "补齐监测", "evidence": "8/14-8/16 无退货记录。",
         "action": "确认拉取范围。"}
      ]
    }"""

    result = await AnswerService().compose(
        _trend_facts(),
        FakeLlmClient(responses=[draft]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.degraded is False, "斜杠日期不应被判成幻觉"


def test_allowed_numbers_includes_date_parts_from_the_facts() -> None:
    """治本：事实包里日期值的成分本身就是可引用的数字。

    只要日期在数据里，模型写成 8月11日 / 8/11 / 08-11 / 十一日 都不该被拦——
    与其枚举模型可能用的每种格式，不如承认这些成分是合法可引用的。
    """

    from app.services.answer_service import _allowed_numbers

    allowed = _allowed_numbers(_trend_facts().query_result)

    for part in ("2026", "8", "11", "17"):
        assert part in allowed, f"日期成分 {part} 应当可被引用"
