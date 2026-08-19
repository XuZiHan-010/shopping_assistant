from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.llm.client import LlmBudget
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricPayload
from app.repositories.analytics import ResultColumn
from app.services.safe_query import QueryResult


def test_extract_json_object_strips_markdown_fence_and_prose() -> None:
    """模型前后加说明时，保留其中完整 JSON 交给既有契约校验。"""

    from app.services.answer_service import extract_json_object

    assert extract_json_object('```json\n{"answer":"x"}\n```') == '{"answer":"x"}'
    assert extract_json_object('好的：{"answer":"x"} 以上。') == '{"answer":"x"}'
    assert extract_json_object('{"answer":"x"}') == '{"answer":"x"}'
    assert extract_json_object("没有花括号") == "没有花括号"


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


async def _attempt(draft_json: str, facts):
    """走生产路径的一次生成尝试：`QualityLoop` 调的就是 `compose_once`。"""

    from app.services.answer_service import AnswerService

    return await AnswerService().compose_once(
        facts,
        FakeLlmClient(responses=[draft_json]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )


async def _issues(draft_json: str, facts) -> list[str]:
    """一次尝试的本地校验结果；解析失败按空正文/非法 JSON 单独断言，不走这里。"""

    from app.services.answer_service import AnswerService

    attempt = await _attempt(draft_json, facts)
    assert attempt.draft is not None, "本用例的草稿应当能解析"
    return AnswerService().validate_issues(attempt.draft, facts)


@pytest.mark.asyncio
async def test_compose_once_returns_a_parsed_draft_for_a_valid_response() -> None:
    attempt = await _attempt(_model_draft(), _facts())

    assert attempt.failure_kind is None
    assert attempt.draft is not None
    assert attempt.draft.answer == "最近一天成交 GMV 为 12.00 元。"
    assert len(attempt.draft.recommendations) == 2
    assert await _issues(_model_draft(), _facts()) == []


@pytest.mark.asyncio
async def test_invalid_json_is_a_retryable_output_failure_not_an_upstream_failure() -> None:
    """非法 JSON 是「模型输出不合格」，必须能被质量循环回喂重试。"""

    from app.services.answer_service import AnswerService

    attempt = await AnswerService().compose_once(
        _facts(),
        FakeLlmClient(behaviour="invalid_json"),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert attempt.draft is None
    assert attempt.failure_kind is None
    assert attempt.raw_text == "这不是 JSON"


@pytest.mark.asyncio
async def test_empty_content_is_a_retryable_output_failure_with_empty_raw_text() -> None:
    """HTTP 成功但正文为空同样可回喂；`raw_text` 为空是循环区分两类提示语的依据。"""

    from app.services.answer_service import AnswerService

    attempt = await AnswerService().compose_once(
        _facts(),
        FakeLlmClient(responses=[""]),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert attempt.draft is None
    assert attempt.failure_kind is None
    assert attempt.raw_text == ""


@pytest.mark.asyncio
async def test_upstream_failure_is_reported_as_upstream_not_as_a_bad_draft() -> None:
    from app.services.answer_service import AnswerService
    from app.services.quality_types import AttemptFailureKind

    attempt = await AnswerService().compose_once(
        _facts(),
        FakeLlmClient(behaviour="timeout"),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert attempt.draft is None
    assert attempt.failure_kind is AttemptFailureKind.UPSTREAM


@pytest.mark.asyncio
async def test_retry_prompt_carries_the_previous_draft_and_its_issues() -> None:
    """回喂是整个循环的价值所在：不带上一版和失败原因，重试等于重掷骰子。"""

    from app.services.answer_service import AnswerService

    llm = FakeLlmClient(responses=[_model_draft()])
    await AnswerService().compose_once(
        _facts(),
        llm,
        LlmBudget(max_calls=4, max_tokens=1_000),
        previous='{"answer":"退货量为 98765 件。"}',
        issues=["以下数字不在查询结果或事实摘要里，不得出现在回答中：98765"],
    )

    assert "98765" in llm.calls[0][1]
    assert "请修复所有问题" in llm.calls[0][1]


@pytest.mark.asyncio
async def test_a_draft_that_sums_a_non_additive_metric_becomes_an_issue() -> None:
    draft = """{
      "answer": "最近三天退货率合计 3.80%。",
      "recommendations": [
        {"title": "关注退货率", "evidence": "1.20", "action": "结合物流排查原因。"},
        {"title": "核对区间", "evidence": "1.50", "action": "确认口径是否符合预期。"}
      ]
    }"""

    issues = await _issues(draft, _non_additive_facts())

    assert any("非加和" in issue for issue in issues)


@pytest.mark.asyncio
async def test_a_draft_that_leaks_an_internal_identifier_becomes_an_issue() -> None:
    draft = """{
      "answer": "本次查询由 1c3b8a2e-4f5d-4a11-9c2a-7d6e5f4b3a21 执行，GMV 为 12.00 元。",
      "recommendations": [
        {"title": "关注成交", "evidence": "GMV 为 12.00 元。", "action": "结合流量继续观察。"},
        {"title": "核对范围", "evidence": "本次结果包含 1 行数据。", "action": "确认日期范围。"}
      ]
    }"""

    issues = await _issues(draft, _facts())

    assert any("标识符" in issue for issue in issues)


@pytest.mark.asyncio
async def test_all_three_kinds_of_problems_are_reported_in_one_pass() -> None:
    """一次说清全部问题，模型下一轮才可能一次改对；遇到第一个就中断会白烧一轮。"""

    draft = """{
      "answer": "退货率合计 3.80%，由 1c3b8a2e-4f5d-4a11-9c2a-7d6e5f4b3a21 执行。",
      "recommendations": [
        {"title": "关注退货率", "evidence": "1.20", "action": "结合物流排查原因。"},
        {"title": "核对区间", "evidence": "1.50", "action": "确认口径是否符合预期。"}
      ]
    }"""

    issues = await _issues(draft, _non_additive_facts())

    assert any("标识符" in issue for issue in issues)
    assert any("非加和" in issue for issue in issues)
    assert any("3.80" in issue for issue in issues)


def test_facts_json_reports_the_non_additive_flag() -> None:
    from app.services.answer_service import AnswerService

    additive = AnswerService().facts_json(_facts())
    non_additive = AnswerService().facts_json(_non_additive_facts())

    assert '"non_additive":false' in additive
    assert '"non_additive":true' in non_additive


@pytest.mark.asyncio
async def test_a_number_missing_from_the_query_result_becomes_an_issue() -> None:
    issues = await _issues(_model_draft().replace("12.00", "99.00"), _facts())

    assert any("99.00" in issue for issue in issues)


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
async def test_dates_written_in_chinese_form_are_citable() -> None:
    """事实包用 ISO 日期，但中文回答里模型自然会写「8月11日」。

    2026-08-17 线上实测：一份完全基于事实的草稿因此被判成幻觉——`_validate` 只剥
    ISO 日期，剩下的 8/11/17 被当作「查询结果外的数字」，整轮回答降级成兜底摘要。
    日期成分是维度值，不是要与聚合结果逐项比对的业务数字，写成哪种格式都一样。
    """

    draft = """{
      "answer": "8月11日退货量为 3 件，8月17日升至 15 件。",
      "recommendations": [
        {"title": "核查退货激增", "evidence": "8月17日退货量为 15 件。",
         "action": "调取当天退货明细。"},
        {"title": "持续观察", "evidence": "8月11日退货量为 3 件。",
         "action": "每日跟踪退货量。"}
      ]
    }"""

    issues = await _issues(draft, _trend_facts())

    assert issues == [], "基于事实的中文日期草稿不应被判成幻觉"


@pytest.mark.asyncio
async def test_business_numbers_outside_the_facts_are_still_rejected() -> None:
    """放行日期成分不能顺带放行编造的业务数字——这道守卫的本职必须保留。"""

    draft = """{
      "answer": "8月11日退货量为 3 件，退款金额达到 98765 元。",
      "recommendations": [
        {"title": "核查退货", "evidence": "8月11日退货量为 3 件。", "action": "调取明细。"},
        {"title": "持续观察", "evidence": "8月17日退货量为 15 件。", "action": "每日跟踪。"}
      ]
    }"""

    issues = await _issues(draft, _trend_facts())

    assert any("98765" in issue for issue in issues), "编造的 98765 必须仍被拦下"


@pytest.mark.asyncio
async def test_the_time_window_restated_from_the_question_is_citable() -> None:
    """模型复述用户问的时间窗口（「最近 7 天」）不是幻觉。

    2026-08-17 线上实测：日期写法修好后仍然降级，唯一越界数字是 7——来自
    「最近7天有记录的退货量中……」和「无法覆盖完整7天趋势」。时长表述与日期同类，
    都是时间成分，不是要与聚合结果逐项比对的业务数字。
    """

    draft = """{
      "answer": "最近7天有记录的退货量中，8月11日为 3 件，8月17日达到 15 件。",
      "recommendations": [
        {"title": "核查退货激增", "evidence": "8月17日退货量为 15 件。",
         "action": "调取当天退货明细。"},
        {"title": "补齐监测", "evidence": "当前数据无法覆盖完整7天趋势。",
         "action": "确认拉取范围是否遗漏。"}
      ]
    }"""

    issues = await _issues(draft, _trend_facts())

    assert issues == [], "复述问题里的时间窗口不应被判成幻觉"


@pytest.mark.asyncio
async def test_dates_written_with_slashes_are_citable() -> None:
    """模型也会把日期写成「8/12」「8/14-8/16」。

    2026-08-18 线上实测：4 次采样有 2 次因此降级，越界数字全是斜杠日期的成分。
    枚举格式是打地鼠，但数据里不存在的空档日期（8/14-8/16）只能靠剥格式覆盖。
    """

    draft = """{
      "answer": "8/11、8/17 分别为 3 件和 15 件，期间 8/14-8/16 无记录。",
      "recommendations": [
        {"title": "核查激增", "evidence": "8/17 退货量为 15 件。",
         "action": "调取当天明细。"},
        {"title": "补齐监测", "evidence": "8/14-8/16 无退货记录。",
         "action": "确认拉取范围。"}
      ]
    }"""

    issues = await _issues(draft, _trend_facts())

    assert issues == [], "斜杠日期不应被判成幻觉"


def test_allowed_numbers_includes_date_parts_from_the_facts() -> None:
    """治本：事实包里日期值的成分本身就是可引用的数字。

    只要日期在数据里，模型写成 8月11日 / 8/11 / 08-11 / 十一日 都不该被拦——
    与其枚举模型可能用的每种格式，不如承认这些成分是合法可引用的。
    """

    from app.services.answer_service import _allowed_numbers

    allowed = _allowed_numbers(_trend_facts().query_result)

    for part in ("2026", "8", "11", "17"):
        assert part in allowed, f"日期成分 {part} 应当可被引用"


def test_derived_summary_numbers_are_citable() -> None:
    from app.schemas.answer import AnswerDraft
    from app.schemas.chat import Recommendation
    from app.services.answer_service import AnswerService

    draft = AnswerDraft(
        answer="合计 18 件，峰值 15 件出现在最新一天，较首期增长 400.0%。",
        recommendations=[
            Recommendation(title="关注峰值", evidence="峰值 15 件。", action="继续观察。"),
            Recommendation(title="关注合计", evidence="合计 18 件。", action="核对趋势。"),
        ],
    )

    assert AnswerService()._validate(draft, _trend_facts()) == []


@pytest.mark.parametrize("field", ["title", "evidence", "action"])
def test_recommendation_fields_cannot_smuggle_numbers_outside_facts(field: str) -> None:
    from app.schemas.answer import AnswerDraft
    from app.schemas.chat import Recommendation
    from app.services.answer_service import AnswerService

    recommendation = {"title": "建议", "evidence": "峰值 15 件。", "action": "继续观察。"}
    recommendation[field] = "建议按 98765 件执行"
    draft = AnswerDraft(
        answer="合计 18 件。",
        recommendations=[Recommendation(**recommendation), Recommendation(**recommendation)],
    )

    issues = AnswerService()._validate(draft, _trend_facts())

    assert any("98765" in issue for issue in issues)


def test_summary_uses_business_date_order_and_is_included_in_fact_package() -> None:
    from app.services.answer_service import AnswerService

    facts = _trend_facts()
    reversed_facts = replace(
        facts,
        query_result=replace(facts.query_result, rows=list(reversed(facts.query_result.rows))),
    )

    summary = AnswerService()._derive_summary(reversed_facts)

    assert summary.total == Decimal("18")
    assert summary.latest_label == "2026-08-17"
    assert summary.latest_value == Decimal("15")
    assert summary.peak_value == Decimal("15")
    assert summary.change_pct == Decimal("400.0")
    assert '"summary"' in AnswerService().facts_json(reversed_facts)


def test_truncated_rows_do_not_produce_derived_summary_numbers() -> None:
    from app.services.answer_service import AnswerService

    facts = _trend_facts()
    summary = AnswerService()._derive_summary(
        replace(facts, query_result=replace(facts.query_result, truncated=True))
    )

    assert summary.total is None
    assert summary.latest_value is None
    assert summary.change_pct is None


def test_fallback_reports_total_latest_and_peak_for_additive_time_series() -> None:
    from app.services.answer_service import AnswerService

    draft = AnswerService().fallback_draft(_trend_facts())

    assert "合计 18" in draft.answer
    assert "最新日期 2026-08-17" in draft.answer
    assert "峰值 15" in draft.answer


def test_fallback_refuses_to_total_a_non_additive_metric() -> None:
    from app.services.answer_service import AnswerService

    draft = AnswerService().fallback_draft(_non_additive_facts())

    assert "不做跨日合计" in draft.answer
    assert "合计为" not in draft.answer


def _category_facts():
    """按类目分组的非时间序列结果：没有可解析日期维度，就不该有「最新/变化率」。"""

    from app.services.answer_service import AnswerFacts

    return AnswerFacts(
        question="各类目退货量分别是多少？",
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
                ResultColumn("category", "类目", "DIMENSION"),
                ResultColumn("return_count", "退货量", "METRIC"),
            ),
            rows=[
                {"category": "女装", "return_count": Decimal("3")},
                {"category": "鞋靴", "return_count": Decimal("15")},
            ],
            total_rows=2,
            truncated=False,
            source_tables=("returns",),
            plan_steps=("按类目汇总退货量",),
            export_spec=None,
            notes=(),
            non_additive=False,
        ),
    )


def test_non_temporal_grouping_has_no_latest_or_change() -> None:
    from app.services.answer_service import AnswerService

    summary = AnswerService()._derive_summary(_category_facts())

    assert summary.latest_label is None
    assert summary.change_pct is None
    assert summary.total is None


def test_fallback_does_not_claim_a_latest_value_for_category_grouping() -> None:
    """把「鞋靴」说成「最新」是纯粹的胡说，非时间分组必须换一套措辞。"""

    from app.services.answer_service import AnswerService

    draft = AnswerService().fallback_draft(_category_facts())

    assert "最新" not in draft.answer
    assert "峰值" not in draft.answer


def test_fallback_marks_truncated_rows_as_preview_without_total() -> None:
    """截断结果只能讲「预览」：拿部分行冒充全量合计，用户拿到的就是错数。"""

    from app.services.answer_service import AnswerService

    facts = _trend_facts()
    draft = AnswerService().fallback_draft(
        replace(facts, query_result=replace(facts.query_result, truncated=True))
    )

    assert "仅展示部分结果" in draft.answer
    assert "合计" not in draft.answer.replace("不对预览行做合计", "")


def test_equivalent_decimal_display_forms_are_citable() -> None:
    """事实里的 15.00 不该把模型常写的「15」判成编造。"""

    from app.services.answer_service import _numeric_forms

    forms = _numeric_forms(Decimal("15.00"))

    assert {"15", "15.0", "15.00"} <= forms
