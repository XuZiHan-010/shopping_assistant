"""结构化意图的白名单与后端截断行为。"""

from __future__ import annotations

from datetime import date

from app.intent.models import DateRange, QueryIntent
from app.intent.whitelist import MAX_DETAIL_LIMIT, MAX_QUERY_DAYS, validate_intent
from app.schemas.chat import AnswerMode, QuestionCategory

TODAY = date(2026, 8, 4)


def _intent(**overrides: object) -> QueryIntent:
    base: dict[str, object] = {
        "answer_mode": AnswerMode.METRIC,
        "category": QuestionCategory.TRADE,
        "metric": "gmv",
        "dimensions": [],
        "filters": {},
        "date_range": DateRange(start=date(2026, 8, 1), end=date(2026, 8, 3)),
        "sort": None,
        "limit": None,
        "followup_reference": False,
        "needs_attachment": False,
    }
    base.update(overrides)
    return QueryIntent.model_validate(base)


def test_valid_intent_is_preserved() -> None:
    """合法意图被改写会使模型的正常结构化输出失真。"""

    result = validate_intent(_intent(), today=TODAY)

    assert result.rejected == ()
    assert result.intent.metric == "gmv"


def test_sql_in_metric_is_rejected() -> None:
    """SQL 流入意图会给后续查询层制造注入入口。"""

    result = validate_intent(_intent(metric="SELECT * FROM orders"), today=TODAY)

    assert any("SQL" in reason for reason in result.rejected)
    assert result.intent.answer_mode is AnswerMode.INVALID


def test_non_metric_code_name_is_rejected() -> None:
    """中文指标名会绕开确定性的 metric_code 白名单。"""

    result = validate_intent(_intent(metric="成交金额"), today=TODAY)

    assert any("metric_code" in reason for reason in result.rejected)
    assert result.intent.answer_mode is AnswerMode.INVALID


def test_non_whitelisted_dimension_is_rejected() -> None:
    """非白名单维度会被 B4 拼入不受控标识符位置。"""

    result = validate_intent(_intent(dimensions=["seller_secret"]), today=TODAY)

    assert any("维度" in reason for reason in result.rejected)


def test_non_whitelisted_filter_is_rejected() -> None:
    """非白名单筛选字段会突破查询字段边界。"""

    result = validate_intent(_intent(filters={"seller_secret": "x"}), today=TODAY)

    assert any("筛选" in reason for reason in result.rejected)


def test_date_range_over_180_days_is_clamped_not_rejected() -> None:
    """日期超限若改为报错，会让正常的长区间提问直接失败。"""

    result = validate_intent(
        _intent(date_range=DateRange(start=date(2024, 1, 1), end=TODAY)), today=TODAY
    )

    assert result.rejected == ()
    assert result.intent.date_range is not None
    assert (
        result.intent.date_range.end - result.intent.date_range.start
    ).days + 1 == MAX_QUERY_DAYS
    assert any("日期" in note for note in result.adjusted)


def test_future_end_date_is_clamped_to_today() -> None:
    """模型常把「最近一年」写成跨到未来的区间；查未来只会得到空结果。"""

    result = validate_intent(
        _intent(date_range=DateRange(start=date(2026, 7, 1), end=date(2027, 3, 1))),
        today=TODAY,
    )

    assert result.rejected == ()
    assert result.intent.date_range is not None
    assert result.intent.date_range.end == TODAY
    assert result.intent.date_range.start == date(2026, 7, 1)
    assert any("未来" in note for note in result.adjusted)


def test_range_entirely_in_the_future_is_rejected() -> None:
    """整段区间都在未来时无区间可截断，继续查询等于返回空数据却不说明原因。"""

    result = validate_intent(
        _intent(date_range=DateRange(start=date(2027, 1, 1), end=date(2027, 3, 1))),
        today=TODAY,
    )

    assert any("未来" in reason for reason in result.rejected)
    assert result.intent.answer_mode is AnswerMode.INVALID


def test_reversed_date_range_is_rejected() -> None:
    """起止颠倒是模型输出错误；替它猜方向会把错误结果当成正常回答。"""

    result = validate_intent(
        _intent(date_range=DateRange(start=date(2026, 8, 3), end=date(2026, 8, 1))),
        today=TODAY,
    )

    assert any("起止" in reason for reason in result.rejected)
    assert result.intent.answer_mode is AnswerMode.INVALID


def test_future_clamp_runs_before_the_180_day_clamp() -> None:
    """先截未来再截 180 天，才能保证最终区间落在有演示数据的范围内。"""

    result = validate_intent(
        _intent(date_range=DateRange(start=date(2024, 1, 1), end=date(2027, 3, 1))),
        today=TODAY,
    )

    assert result.rejected == ()
    assert result.intent.date_range is not None
    assert result.intent.date_range.end == TODAY
    assert (
        result.intent.date_range.end - result.intent.date_range.start
    ).days + 1 == MAX_QUERY_DAYS


def test_limit_over_maximum_is_clamped_not_rejected() -> None:
    """明细行数超限若未覆盖，会导致后续导出和查询膨胀。"""

    result = validate_intent(_intent(answer_mode=AnswerMode.DETAIL, limit=100_000), today=TODAY)

    assert result.rejected == ()
    assert result.intent.limit == MAX_DETAIL_LIMIT
    assert any("limit" in note for note in result.adjusted)


def test_metric_whitelist_matches_metric_seed() -> None:
    """白名单与 Seed 漂移会使正式指标在意图层静默失效。"""

    from app.intent.whitelist import METRIC_WHITELIST
    from app.metrics.seed import METRIC_SEED

    assert {item.metric_code for item in METRIC_SEED} == set(METRIC_WHITELIST)


def test_b4_metric_and_dimension_contract_is_implemented_in_b3_whitelists() -> None:
    """B3 的意图边界必须和 B4 的受控查询字段共享同一套公开契约。"""

    from app.intent.whitelist import DIMENSION_WHITELIST, FILTER_WHITELIST, METRIC_WHITELIST

    assert {
        "gmv",
        "order_count",
        "paying_user_count",
        "successful_order_count",
        "refund_count",
        "refund_amount",
        "return_count",
        "return_rate",
        "support_ticket_count",
    } == METRIC_WHITELIST
    assert {
        "date",
        "product",
        "category",
        "order_status",
        "refund_reason",
        "return_reason",
        "return_status",
        "ticket_status",
    } == DIMENSION_WHITELIST
    assert FILTER_WHITELIST == DIMENSION_WHITELIST
