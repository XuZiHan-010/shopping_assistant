from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.llm.client import STRUCTURED_CALL_OPTIONS, LlmBudget
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
async def test_compose_once_requests_structured_json_output_with_thinking_disabled() -> None:
    """草稿生成是四处结构化 JSON 调用之外遗漏的第五处：这里曾经用默认选项，
    推理模式不关，也不强制 json_object，容易被隐藏的 reasoning token 挤爆
    max_tokens 而截断或返回空 content。"""

    llm = FakeLlmClient(responses=[_model_draft()])
    await _attempt_with(llm, _facts())

    assert llm.call_options == [STRUCTURED_CALL_OPTIONS]


@pytest.mark.asyncio
async def test_a_corrupted_upstream_payload_is_reported_as_upstream_not_a_passed_draft() -> None:
    """DeepSeek 返回损坏 payload 时，`LlmResult.text` 是调用方传入的确定性兜底
    JSON——语法合法但不是模型的真实输出。曾经的实现把 BAD_PAYLOAD 排除在「当
    失败处理」之外，于是这段兜底 JSON 被当成真实草稿走完质量循环，最终对用户
    显示 quality_status=PASSED，完全看不出模型输出其实已被丢弃（违反 R7）。"""

    from app.services.answer_service import AnswerService
    from app.services.quality_types import AttemptFailureKind

    attempt = await AnswerService().compose_once(
        _facts(),
        FakeLlmClient(behaviour="bad_payload"),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert attempt.draft is None
    assert attempt.failure_kind is AttemptFailureKind.UPSTREAM


async def _attempt_with(llm: FakeLlmClient, facts):
    from app.services.answer_service import AnswerService

    return await AnswerService().compose_once(facts, llm, LlmBudget(max_calls=4, max_tokens=1_000))


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


def _comparison_facts(*, change_ratio: Decimal | None = Decimal("50.0")):
    """D3 裁定：环比/同比事实包，两期数值与变化率均由查询层预先算好。"""

    from datetime import date

    from app.intent.models import ComparisonMode, DateRange
    from app.services.answer_service import AnswerFacts
    from app.services.safe_query import ComparisonResult

    return AnswerFacts(
        question="这个月GMV相比上个月环比变化多少",
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
            rows=[{"gmv": Decimal("150.00")}],
            total_rows=1,
            truncated=False,
            source_tables=("orders",),
            plan_steps=("按月汇总成交 GMV",),
            export_spec=None,
            notes=(),
            non_additive=False,
            comparison=ComparisonResult(
                mode=ComparisonMode.PREVIOUS_PERIOD,
                current_range=DateRange(start=date(2026, 8, 1), end=date(2026, 8, 22)),
                baseline_range=DateRange(start=date(2026, 7, 1), end=date(2026, 7, 22)),
                current_value=Decimal("150.00"),
                baseline_value=Decimal("100.00"),
                change_ratio=change_ratio,
            ),
        ),
    )


def test_comparison_change_ratio_computed_by_the_backend_is_citable() -> None:
    """后端已经算出 50.0%，模型只是复述它，不应被判成编造数字。"""

    from app.schemas.answer import AnswerDraft
    from app.schemas.chat import Recommendation
    from app.services.answer_service import AnswerService

    draft = AnswerDraft(
        answer="本月成交 GMV 为 150.00 元，环比上月的 100.00 元增长 50.0%。",
        recommendations=[
            Recommendation(title="关注环比", evidence="环比增长 50.0%。", action="持续观察。"),
            Recommendation(title="核对基期", evidence="上月为 100.00 元。", action="核对口径。"),
        ],
    )

    assert AnswerService()._validate(draft, _comparison_facts()) == []


def test_comparison_ratio_the_model_invents_itself_is_rejected() -> None:
    """基期无法计算变化率时（change_ratio=None），模型不得自己编一个百分比。

    这正是 R4「模型不得推算对比结果」的落点：编出的 31.8% 不在允许集合里，
    必须被 `_validate` 拦下，而不是被当成正常回答放行。
    """

    from app.schemas.answer import AnswerDraft
    from app.schemas.chat import Recommendation
    from app.services.answer_service import AnswerService

    draft = AnswerDraft(
        answer="本月成交 GMV 环比增长约 31.8%。",
        recommendations=[
            Recommendation(title="关注环比", evidence="环比增长 31.8%。", action="持续观察。"),
            Recommendation(title="核对口径", evidence="基期数据缺失。", action="核对时间范围。"),
        ],
    )

    issues = AnswerService()._validate(draft, _comparison_facts(change_ratio=None))

    assert any("31.8" in issue for issue in issues)


def test_facts_json_carries_the_comparison_object_for_the_model_to_cite() -> None:
    from app.services.answer_service import AnswerService

    payload = AnswerService().facts_json(_comparison_facts())

    assert '"comparison"' in payload
    assert '"change_ratio":"50.0"' in payload
    assert '"baseline_value":"100.00"' in payload


def test_fallback_reports_both_periods_and_the_change_ratio() -> None:
    from app.services.answer_service import AnswerService

    draft = AnswerService().fallback_draft(_comparison_facts())

    assert "150.00" in draft.answer
    assert "100.00" in draft.answer
    assert "50.0%" in draft.answer


def test_fallback_explains_when_the_baseline_makes_the_ratio_uncomputable() -> None:
    """基期算不出比例时，兜底文案必须如实说明，不能假装给出了一个环比结论（R7）。"""

    from app.services.answer_service import AnswerService

    draft = AnswerService().fallback_draft(_comparison_facts(change_ratio=None))

    assert "无法计算变化率" in draft.answer
    assert "%" not in draft.answer


# ---------------------------------------------------------------------------
# Task 5：语言无关的本地校验——聚合断言与日期区间一致性对英文回答同样生效。
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    from app.services.answer_service import AnswerService

    return AnswerService()


def _draft_with_answer(answer: str):
    from app.schemas.answer import AnswerDraft
    from app.schemas.chat import Recommendation

    return AnswerDraft(
        answer=answer,
        recommendations=[
            Recommendation(title="Note", evidence=answer, action="Review the range."),
            Recommendation(title="Check", evidence=answer, action="Confirm the date range."),
        ],
    )


def _facts_without_total():
    """非加和指标、多行结果——聚合断言检查的结构前提，与语言无关。"""

    from app.services.answer_service import AnswerFacts

    return AnswerFacts(
        question="What are the refund amounts for the last 7 days?",
        metric=MetricPayload(
            metric_code="refund_amount",
            display_name="Refund amount",
            unit="CNY",
            definition="The refund amount of refund records, not summable across the period.",
            source="Borough Metric Catalog",
            owner="Business Analytics",
            status="ACTIVE",
            generated=False,
            notice=None,
        ),
        query_result=QueryResult(
            columns=(
                ResultColumn("date", "Date", "DIMENSION"),
                ResultColumn("refund_amount", "Refund amount", "METRIC"),
            ),
            rows=[
                {"date": "2026-08-05", "refund_amount": Decimal("4000.00")},
                {"date": "2026-08-06", "refund_amount": Decimal("4500.00")},
                {"date": "2026-08-07", "refund_amount": Decimal("3500.00")},
            ],
            total_rows=3,
            truncated=False,
            source_tables=("refunds",),
            plan_steps=("Aggregate refund amount by day",),
            export_spec=None,
            notes=(),
            non_additive=True,
        ),
    )


def test_additive_claim_check_catches_english_total_claim(service) -> None:
    """英文 total/combined 之类的合计断言必须与中文『合计』受同等校验。"""

    issues = service.validate_issues(
        draft=_draft_with_answer("Refunds totalled 12,000 CNY over the last 7 days"),
        facts=_facts_without_total(),
    )

    assert issues, "英文合计断言必须触发非加和指标校验"
    assert any("非加和" in issue for issue in issues)


def _facts_for_last_3_days():
    """真实查询区间只有 2026-08-05 至 2026-08-07 这 3 天。

    刻意让草稿会用到的数字（1、7）都能在事实包里找到"看似合法"的出处
    （行内数值 1、日期成分 7），这样如果日期区间一致性校验没有真正生效，
    通用的"数字未出现在事实包"校验也不会意外把这条用例救回来——确保这条
    测试只在日期区间比对本身工作时才会通过。
    """

    from app.services.answer_service import AnswerFacts

    return AnswerFacts(
        question="What is the refund amount for the last 3 days?",
        metric=MetricPayload(
            metric_code="refund_amount",
            display_name="Refund amount",
            unit="CNY",
            definition="The refund amount of refund records.",
            source="Borough Metric Catalog",
            owner="Business Analytics",
            status="ACTIVE",
            generated=False,
            notice=None,
        ),
        query_result=QueryResult(
            columns=(
                ResultColumn("date", "Date", "DIMENSION"),
                ResultColumn("refund_amount", "Refund amount", "METRIC"),
            ),
            rows=[
                {"date": "2026-08-05", "refund_amount": Decimal("1")},
                {"date": "2026-08-06", "refund_amount": Decimal("2")},
                {"date": "2026-08-07", "refund_amount": Decimal("7")},
            ],
            total_rows=3,
            truncated=False,
            source_tables=("refunds",),
            plan_steps=("Aggregate refund amount by day",),
            export_spec=None,
            notes=(),
            non_additive=False,
        ),
    )


def test_date_consistency_check_understands_english_ranges(service) -> None:
    """英文 "from X to Y" 日期区间必须与实际查询范围比对，而不是被直接放行。"""

    issues = service.validate_issues(
        draft=_draft_with_answer("From Aug 1 to Aug 7 the refund amount rose"),
        facts=_facts_for_last_3_days(),
    )

    assert issues, "陈述的日期区间超出实际查询范围（2026-08-05~07）应当被拦下"


def test_date_consistency_check_allows_a_range_contained_in_the_facts(service) -> None:
    """区间落在事实包范围内时不该被误判——中英文校验必须一样宽松，不只是一样严格。"""

    issues = service.validate_issues(
        draft=_draft_with_answer("From Aug 5 to Aug 7 the refund amount rose"),
        facts=_facts_for_last_3_days(),
    )

    assert issues == []


def test_date_consistency_check_still_works_for_chinese_ranges(service) -> None:
    """中文『8月1日至8月7日』式显式区间同样要与实际范围比对——校验逻辑双语共用。"""

    issues = service.validate_issues(
        draft=_draft_with_answer("8月1日至8月7日退款金额有所上升"),
        facts=_facts_for_last_3_days(),
    )

    assert issues, "中文显式区间超出实际范围同样应当被拦下"


# ---------------------------------------------------------------------------
# 复核 Finding 1：聚合断言的英文匹配改成词边界正则，不能再用子串 `in` 判断——
# 子串匹配曾经把 "totally"（"total" 的无关前缀）也判成合计断言。
# ---------------------------------------------------------------------------


def test_additive_claim_check_does_not_misfire_on_an_unrelated_word_sharing_a_prefix(
    service,
) -> None:
    """"totally" 与 "total" 共享前缀但语义无关，词边界匹配不能把它误判成合计
    断言——这正是子串匹配版本会产生的假阳性（reviewer Finding 1）。
    """

    issues = service.validate_issues(
        draft=_draft_with_answer("Refund amounts look totally normal, nothing to report."),
        facts=_facts_without_total(),
    )

    assert issues == []


def test_additive_claim_check_still_treats_combined_as_a_signal_word(service) -> None:
    """"combined" 作为独立触发词，即使出现在 "combined with" 这类连接短语里
    也会命中——这是已知的、有意接受的残余误判风险（reviewer 标记为 Minor）：
    区分"回答把多天数值合并成一个结论"和"combined with 式无关连接词"需要
    语义理解，超出词边界正则能覆盖的范围，不在本任务治理目标内，这里只是
    把当前行为显式锁定成一条可读的回归测试。
    """

    issues = service.validate_issues(
        draft=_draft_with_answer(
            "Combined with strong marketing, refund rates for each day stayed low"
        ),
        facts=_facts_without_total(),
    )

    assert any("非加和" in issue for issue in issues)


# ---------------------------------------------------------------------------
# 复核 Finding 2：相对时长断言（"last N days"/"最近 N 天"）过去完全没有任何
# 代码路径与实际查询区间比对，是与"两个显式日期 token 需要紧邻"这条已知局限
# 完全不同的、未披露的缺口。
# ---------------------------------------------------------------------------


def _facts_for_a_3_day_window_with_a_thirty_value():
    """与 `_facts_for_last_3_days` 同样的 3 天真实窗口（2026-08-05~07），但
    第三天的指标值恰好是 30——这样草稿里出现的 "30" 本身就能在事实包里找到
    "看似合法"的出处，通用的"数字未出现在事实包"校验不会意外把
    "最近 30 天"这类越界时长断言的测试用例救回来，确保测试只在相对时长
    一致性逻辑本身生效时才会通过。
    """

    from app.services.answer_service import AnswerFacts

    return AnswerFacts(
        question="What is the refund amount for the last 3 days?",
        metric=MetricPayload(
            metric_code="refund_amount",
            display_name="Refund amount",
            unit="CNY",
            definition="The refund amount of refund records.",
            source="Borough Metric Catalog",
            owner="Business Analytics",
            status="ACTIVE",
            generated=False,
            notice=None,
        ),
        query_result=QueryResult(
            columns=(
                ResultColumn("date", "Date", "DIMENSION"),
                ResultColumn("refund_amount", "Refund amount", "METRIC"),
            ),
            rows=[
                {"date": "2026-08-05", "refund_amount": Decimal("1")},
                {"date": "2026-08-06", "refund_amount": Decimal("2")},
                {"date": "2026-08-07", "refund_amount": Decimal("30")},
            ],
            total_rows=3,
            truncated=False,
            source_tables=("refunds",),
            plan_steps=("Aggregate refund amount by day",),
            export_spec=None,
            notes=(),
            non_additive=False,
        ),
    )


def test_date_consistency_check_flags_a_mismatched_relative_duration_in_english(service) -> None:
    """"over the last 30 days" 远超实际只查到的 3 天范围，必须被拦下。"""

    issues = service.validate_issues(
        draft=_draft_with_answer("Over the last 30 days, the refund amount rose"),
        facts=_facts_for_a_3_day_window_with_a_thirty_value(),
    )

    assert issues, "宣称的 30 天窗口远超实际查询到的 3 天范围，应当被拦下"


def test_date_consistency_check_flags_a_mismatched_relative_duration_in_chinese(service) -> None:
    """中文『最近30天』式相对时长同样要与实际范围比对——校验逻辑双语共用。"""

    issues = service.validate_issues(
        draft=_draft_with_answer("最近30天退款金额呈上升趋势"),
        facts=_facts_for_a_3_day_window_with_a_thirty_value(),
    )

    assert issues, "宣称的 30 天窗口远超实际查询到的 3 天范围，应当被拦下"


def test_date_consistency_check_allows_a_relative_duration_that_matches_the_facts(
    service,
) -> None:
    """陈述的时长与实际查询覆盖的天数一致时不该被误判。"""

    issues = service.validate_issues(
        draft=_draft_with_answer("Over the last 3 days, the refund amount rose"),
        facts=_facts_for_last_3_days(),
    )

    assert issues == []


def test_date_consistency_check_does_not_crash_on_an_absurdly_large_hallucinated_duration(
    service,
) -> None:
    """模型幻觉出「最近 1000 万天」这类离谱数字时，`date - timedelta(...)` 一旦
    超出 `date` 能表示的公元 1~9999 年范围就会抛出未捕获的 `OverflowError`
    （复核 Finding：这个异常不在 `compose_once` 的 try/except 覆盖范围内，
    会直接崩掉质量循环）。这条离谱声明本身不是真实时长表述，校验应当稳妥地
    跳过它（不产出这条 issue，也绝不能抛异常），而不是尝试解析后再崩溃。
    """

    issues = service.validate_issues(
        draft=_draft_with_answer("Over the last 10000000 days, the refund amount rose"),
        facts=_facts_for_last_3_days(),
    )

    assert isinstance(issues, list)
