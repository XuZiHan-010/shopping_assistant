"""受控查询与仓储之间的异常边界和入参夹紧。

这些性质不需要真实数据库：要验证的正是「不合法的东西根本到不了 SQL」，
以及「仓储真的抛了异常时用户拿到可见拒绝而不是 500」。用假仓储把仓储调用
记录下来，比连库更能直接断言「这条查询有没有被发出去」。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.core.security import MerchantContext
from app.intent.models import DateRange, QueryIntent
from app.intent.whitelist import validate_intent
from app.repositories.analytics import AggregateResult, AnalyticsRepository, DetailResult
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services.safe_query import SafeQueryService, UnsupportedQueryError

NOW = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
DAY = date(2026, 8, 3)


class _RecordingRepository:
    """记录调用参数的假仓储；`error` 非空时模拟数据库层抛错。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.aggregate_calls: list[dict[str, Any]] = []
        self.detail_calls: list[dict[str, Any]] = []

    async def aggregate(self, **kwargs: Any) -> AggregateResult:
        self.aggregate_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return AggregateResult(columns=(), rows=[], source_tables=("orders",))

    async def detail(self, **kwargs: Any) -> DetailResult:
        self.detail_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return DetailResult(
            columns=(), rows=[], total_rows=0, truncated=False, source_tables=("orders",)
        )


def _service(repository: _RecordingRepository) -> SafeQueryService:
    return SafeQueryService(
        cast(AnalyticsRepository, repository), business_timezone="Asia/Shanghai"
    )


def _intent(**overrides: object) -> QueryIntent:
    base: dict[str, object] = {
        "answer_mode": AnswerMode.METRIC,
        "category": QuestionCategory.TRADE,
        "metric": "gmv",
        "dimensions": [],
        "filters": {},
        "date_range": DateRange(start=DAY, end=DAY),
    }
    base.update(overrides)
    return QueryIntent.model_validate(base)


def _context() -> MerchantContext:
    return MerchantContext(merchant_id=uuid4())


def _assert_safe_reason(reason: str) -> None:
    """拒绝原因会直接展示给商家：不能带数据库异常原文、表名、列名或驱动名。"""

    assert "SELECT" not in reason.upper()
    assert "psycopg" not in reason.lower()
    for forbidden in ("orders", "order_items", "refunds", "returns", "business_date", "statement"):
        assert forbidden not in reason


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["昨天", "最近七天", "2026-13-45", "2026/08/03"])
async def test_unparsable_date_filter_never_reaches_sql(value: str) -> None:
    """B3 只校验筛选字段的**键**，值是模型自由文本。

    `date` 会落到一个 `date` 类型的列上，「昨天」这类中文时间表达传到
    PostgreSQL 就是 `invalid input syntax for type date`，一路冒泡成 500。
    模型确实在抽取中文时间表达，这条路径不罕见。
    """

    repository = _RecordingRepository()

    with pytest.raises(UnsupportedQueryError) as raised:
        await _service(repository).execute(_context(), _intent(filters={"date": value}), now=NOW)

    assert repository.aggregate_calls == [], "非法日期值不能被发到仓储"
    assert value not in raised.value.reason, "拒绝原因不回显模型给的原始值"
    _assert_safe_reason(raised.value.reason)


@pytest.mark.asyncio
async def test_unparsable_date_filter_is_refused_on_the_detail_path_too() -> None:
    """明细路径也走同一道值校验，而不是靠「日期不属于本表」这条别的规则顺带挡住。"""

    repository = _RecordingRepository()

    with pytest.raises(UnsupportedQueryError) as raised:
        await _service(repository).execute(
            _context(),
            _intent(answer_mode=AnswerMode.DETAIL, metric=None, filters={"date": "上个月"}),
            now=NOW,
        )

    assert repository.detail_calls == []
    assert "2026" in raised.value.reason, "应命中日期格式的拒绝原因，而不是别的规则"


@pytest.mark.asyncio
async def test_valid_iso_date_filter_still_passes_through() -> None:
    """校验的是「能不能解析成日期」，不是把日期筛选整个禁掉。"""

    repository = _RecordingRepository()

    await _service(repository).execute(_context(), _intent(filters={"date": "2026-08-03"}), now=NOW)

    assert repository.aggregate_calls[0]["filters"] == {"date": "2026-08-03"}


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [-1, 0])
async def test_non_positive_limit_is_clamped_before_reaching_sql(limit: int) -> None:
    """`QueryIntent.limit` 没有下界，B3 白名单也只截上界。

    `.limit(-1)` 在 PostgreSQL 上直接报错 → 500。这里夹紧到合法区间，
    而不是让一个模型笔误变成服务端错误。
    """

    repository = _RecordingRepository()

    await _service(repository).execute(
        _context(),
        _intent(answer_mode=AnswerMode.DETAIL, metric=None, limit=limit),
        now=NOW,
    )

    assert repository.detail_calls[0]["limit"] >= 1


@pytest.mark.asyncio
async def test_detail_export_spec_keeps_the_verified_query_scope() -> None:
    """导出必须重放本次已验证的表、筛选与日期语义，而不是重新猜查询条件。"""

    repository = _RecordingRepository()

    result = await _service(repository).execute(
        _context(),
        _intent(
            answer_mode=AnswerMode.DETAIL,
            metric=None,
            filters={"order_status": "PAID"},
        ),
        now=NOW,
    )

    assert result.export_spec is not None
    assert result.export_spec.table == "orders"
    assert result.export_spec.filters == (("order_status", "PAID"),)
    assert result.export_spec.date_filtered is True


@pytest.mark.asyncio
async def test_invalid_cross_business_plan_runs_the_normal_detail_fallback() -> None:
    repository = _RecordingRepository()
    invalid = QueryIntent.model_validate(
        {
            "answer_mode": AnswerMode.DETAIL,
            "category": QuestionCategory.TRADE,
            "metric": None,
            "dimensions": [],
            "filters": {},
            "date_range": {"start": DAY.isoformat(), "end": DAY.isoformat()},
            "cross_business_plan": {"plan_type": "UNKNOWN", "sub_order_no": "NO-1"},
        }
    )
    validated = validate_intent(invalid, today=DAY)

    result = await _service(repository).execute(_context(), validated.intent, now=NOW)

    assert validated.intent.answer_mode is AnswerMode.DETAIL
    assert validated.intent.cross_business_plan is None
    assert any("跨业务" in note for note in validated.adjusted)
    assert repository.detail_calls, "非法计划必须实际执行普通明细查询"
    assert result.source_tables == ("orders",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        SQLAlchemyError("connection closed"),
        OperationalError(
            "SELECT orders.business_date FROM orders",
            {},
            Exception("canceling statement due to statement timeout"),
        ),
    ],
    ids=["generic", "statement-timeout"],
)
async def test_repository_failure_becomes_a_visible_refusal_not_a_500(error: Exception) -> None:
    """仓储抛出的任何数据库异常都必须在这里收口。

    不收口的话它会一路上抛到 `ChatService._abort` → 全局处理器 → 500，
    合法意图的用户拿到的是服务端错误而不是可见降级——statement timeout
    这条本阶段专门加过的防护也一样会以 500 呈现。
    """

    repository = _RecordingRepository(error=error)

    with pytest.raises(UnsupportedQueryError) as raised:
        await _service(repository).execute(_context(), _intent(), now=NOW)

    _assert_safe_reason(raised.value.reason)
    assert "timeout" not in raised.value.reason.lower()


@pytest.mark.asyncio
async def test_detail_repository_failure_becomes_a_visible_refusal_too() -> None:
    repository = _RecordingRepository(error=SQLAlchemyError("connection closed"))

    with pytest.raises(UnsupportedQueryError) as raised:
        await _service(repository).execute(
            _context(), _intent(answer_mode=AnswerMode.DETAIL, metric=None), now=NOW
        )

    _assert_safe_reason(raised.value.reason)
