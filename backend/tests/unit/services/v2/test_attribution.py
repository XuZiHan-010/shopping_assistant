"""N3 阶段 C Task 1：业绩洞察与归因（`services/v2/attribution.py`）。

只测确定性业务逻辑本身（等长可比周期、绝对贡献值降级、图表点上限、退款口径隔离），
不重复测 `SafeQueryService`/`AnalyticsRepository` 已经用真实 PostgreSQL 验证过的 SQL 层——
这里用一个可编程的假 `SafeQueryService` 替身驱动 `AttributionService`，符合计划 Task 1
步骤 1 伪代码的 `tool` 抽象层级（不是逐字翻译伪代码里的 mock 调用）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.analytics.contract import METRIC_SPECS
from app.core.security import MerchantContext
from app.intent.models import QueryIntent
from app.repositories.analytics import ResultColumn
from app.services.safe_query import ComparisonResult, QueryResult, UnsupportedQueryError
from app.services.v2.attribution import (
    MAX_SINGLE_SERIES_POINTS,
    AttributionService,
    ChartPointLimitExceeded,
    DataSource,
)

MERCHANT_ID = UUID("00000000-0000-4000-8000-000000000101")
WEDNESDAY = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)  # 本周三；本周已过 3 天
# UTC 周日 20:00 = 上海周一 04:00：UTC 日期比业务日期早一天，且跨周。
CROSS_DAY = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)


@dataclass
class ScriptedResult:
    intent: QueryIntent
    result: QueryResult


class FakeSafeQueryService:
    """按调用顺序回放脚本化结果；不解释 intent，只记录并原样返回。"""

    def __init__(self, results: list[QueryResult]) -> None:
        self._results = list(results)
        self.calls: list[QueryIntent] = []

    async def execute(
        self, context: MerchantContext, intent: QueryIntent, *, now: datetime, keywords=()
    ) -> QueryResult:
        del context, now, keywords
        self.calls.append(intent)
        return self._results.pop(0)


def _columns(metric_code: str) -> tuple[ResultColumn, ...]:
    return (ResultColumn(key=metric_code, label=metric_code, kind="METRIC"),)


def _metric_result(
    metric_code: str,
    value: Decimal,
    *,
    source_tables: tuple[str, ...] = ("orders",),
    comparison: ComparisonResult | None = None,
) -> QueryResult:
    return QueryResult(
        columns=_columns(metric_code),
        rows=[{metric_code: value}],
        total_rows=1,
        truncated=False,
        source_tables=source_tables,
        plan_steps=(f"聚合 {metric_code}",),
        export_spec=None,
        notes=(),
        non_additive=not METRIC_SPECS[metric_code].additive,
        comparison=comparison,
    )


def _segmented_result(metric_code: str, segments: list[tuple[str, Decimal]]) -> QueryResult:
    return QueryResult(
        columns=(
            ResultColumn(key="category", label="类目", kind="DIMENSION"),
            ResultColumn(key=metric_code, label=metric_code, kind="METRIC"),
        ),
        rows=[{"category": name, metric_code: value} for name, value in segments],
        total_rows=len(segments),
        truncated=False,
        source_tables=("orders",),
        plan_steps=("聚合",),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


def _context() -> MerchantContext:
    return MerchantContext(merchant_id=MERCHANT_ID)


def _date_series_result(metric_code: str, points: list[tuple[date, Decimal]]) -> QueryResult:
    return QueryResult(
        columns=(
            ResultColumn(key="date", label="日期", kind="DIMENSION"),
            ResultColumn(key=metric_code, label=metric_code, kind="METRIC"),
        ),
        rows=[{"date": day, metric_code: value} for day, value in points],
        total_rows=len(points),
        truncated=False,
        source_tables=("orders",),
        plan_steps=("按日聚合",),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


# --- 等长可比周期 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incomplete_week_uses_equal_length_comparison() -> None:
    """本周只过了 3 天时，归因先试「本周前 3 天 vs 上周前 3 天」，而不是整周对比。"""

    fake = FakeSafeQueryService(
        [
            _segmented_result("gross_gmv", [("女装", Decimal("500")), ("男装", Decimal("300"))]),
            _segmented_result("gross_gmv", [("女装", Decimal("600")), ("男装", Decimal("250"))]),
        ]
    )
    service = AttributionService(fake)
    result = await service.attribute_change(
        _context(), metric="gross_gmv", dimension="category", now=WEDNESDAY, business_timezone="UTC"
    )
    assert result.stopped is False
    assert result.comparison_label == ("本周前 3 天", "上周前 3 天")
    # 两次调用的日期范围长度必须相等（等长可比周期的核心约束）。
    current_range = fake.calls[0].date_range
    baseline_range = fake.calls[1].date_range
    assert current_range is not None and baseline_range is not None
    assert (current_range.end - current_range.start) == (baseline_range.end - baseline_range.start)
    assert (current_range.start, current_range.end) == (date(2026, 9, 21), date(2026, 9, 23))
    assert (baseline_range.start, baseline_range.end) == (date(2026, 9, 14), date(2026, 9, 16))


@pytest.mark.asyncio
async def test_today_is_taken_in_business_timezone_across_utc_midnight() -> None:
    """上海 00:00–08:00 时 UTC 仍是前一天；「今天」必须按业务时区取，与首页同一周期。"""

    fake = FakeSafeQueryService(
        [
            _segmented_result("gross_gmv", [("女装", Decimal("500"))]),
            _segmented_result("gross_gmv", [("女装", Decimal("400"))]),
        ]
    )
    result = await AttributionService(fake).attribute_change(
        _context(),
        metric="gross_gmv",
        dimension="category",
        now=CROSS_DAY,
        business_timezone="Asia/Shanghai",
    )
    current_range = fake.calls[0].date_range
    baseline_range = fake.calls[1].date_range
    assert current_range is not None and baseline_range is not None
    assert (current_range.start, current_range.end) == (date(2026, 9, 28), date(2026, 9, 28))
    assert (baseline_range.start, baseline_range.end) == (date(2026, 9, 21), date(2026, 9, 21))
    assert result.comparison_label == ("本周前 1 天", "上周前 1 天")
    assert result.data_cutoff == date(2026, 9, 28)


@pytest.mark.asyncio
async def test_naive_now_is_rejected() -> None:
    """无时区的时刻无法换算业务日（会被当成服务器本地时间），直接拒绝。"""

    with pytest.raises(ValueError):
        await AttributionService(FakeSafeQueryService([])).attribute_change(
            _context(),
            metric="gross_gmv",
            dimension="category",
            now=datetime(2026, 9, 27, 20, 0),
            business_timezone="Asia/Shanghai",
        )


@pytest.mark.asyncio
async def test_data_gap_stops_attribution_and_says_where() -> None:
    """基期数据缺口时停止归因并说明停在哪一步，而不是继续算出误导性的数字。"""

    fake = FakeSafeQueryService(
        [
            _segmented_result("gross_gmv", [("女装", Decimal("500"))]),
            _segmented_result("gross_gmv", []),  # 基期无数据：数据缺口
        ]
    )
    service = AttributionService(fake)
    result = await service.attribute_change(
        _context(), metric="gross_gmv", dimension="category", now=WEDNESDAY, business_timezone="UTC"
    )
    assert result.stopped is True
    assert result.stopped_reason is not None and "基期" in result.stopped_reason


# --- 绝对贡献值降级 -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_near_zero_change_reports_absolute_contribution() -> None:
    """整体变化接近零或正负抵消时改报绝对贡献值，不计算占比。"""

    fake = FakeSafeQueryService(
        [
            # 当期：女装 +500，男装 -480，合计 +20（接近零）
            _segmented_result("gross_gmv", [("女装", Decimal("1500")), ("男装", Decimal("800"))]),
            _segmented_result("gross_gmv", [("女装", Decimal("1000")), ("男装", Decimal("1280"))]),
        ]
    )
    service = AttributionService(fake)
    result = await service.attribute_change(
        _context(), metric="gross_gmv", dimension="category", now=WEDNESDAY, business_timezone="UTC"
    )
    assert result.mode == "ABSOLUTE_CONTRIBUTION"
    assert all(segment.share is None for segment in result.segments)
    assert all(segment.absolute_contribution is not None for segment in result.segments)


@pytest.mark.asyncio
async def test_clear_swing_reports_share_not_just_absolute() -> None:
    """整体变化明显时正常报告占比（与上一个用例的降级路径区分）。"""

    fake = FakeSafeQueryService(
        [
            _segmented_result("gross_gmv", [("女装", Decimal("500")), ("男装", Decimal("300"))]),
            _segmented_result("gross_gmv", [("女装", Decimal("1000")), ("男装", Decimal("300"))]),
        ]
    )
    service = AttributionService(fake)
    result = await service.attribute_change(
        _context(), metric="gross_gmv", dimension="category", now=WEDNESDAY, business_timezone="UTC"
    )
    assert result.mode == "SHARE"
    women = next(segment for segment in result.segments if segment.name == "女装")
    assert women.share is not None and women.share > Decimal("0.9")


@pytest.mark.asyncio
async def test_net_gmv_attribution_subtracts_refunds_per_category_in_backend() -> None:
    fake = FakeSafeQueryService(
        [
            _segmented_result("gross_gmv", [("女装", Decimal("500")), ("男装", Decimal("300"))]),
            _segmented_result("refund_amount", [("女装", Decimal("100"))]),
            _segmented_result("gross_gmv", [("女装", Decimal("600")), ("男装", Decimal("250"))]),
            _segmented_result("refund_amount", [("女装", Decimal("20")), ("男装", Decimal("10"))]),
        ]
    )
    result = await AttributionService(fake).attribute_change(
        _context(), metric="net_gmv", dimension="category", now=WEDNESDAY, business_timezone="UTC"
    )
    assert result.stopped is False
    women = next(segment for segment in result.segments if segment.name == "女装")
    men = next(segment for segment in result.segments if segment.name == "男装")
    assert (women.current_value, women.baseline_value) == (Decimal("400"), Decimal("580"))
    assert (men.current_value, men.baseline_value) == (Decimal("300"), Decimal("240"))
    assert [call.metric for call in fake.calls] == [
        "gross_gmv",
        "refund_amount",
        "gross_gmv",
        "refund_amount",
    ]
    assert result.data_cutoff == WEDNESDAY.date()
    assert result.source == DataSource.REALTIME
    assert result.definition_version


@pytest.mark.asyncio
async def test_attribution_rejects_truncated_category_results() -> None:
    partial = replace(
        _segmented_result("gross_gmv", [("女装", Decimal("500"))]), truncated=True
    )
    service = AttributionService(FakeSafeQueryService([partial]))
    with pytest.raises(ChartPointLimitExceeded, match="缩小"):
        await service.attribute_change(
            _context(),
            metric="gross_gmv",
            dimension="category",
            now=WEDNESDAY,
            business_timezone="UTC",
        )


# --- 响应必带三项 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_always_carries_cutoff_source_and_version() -> None:
    fake = FakeSafeQueryService([_metric_result("gross_gmv", Decimal("12000"))])
    service = AttributionService(fake)
    result = await service.query_metrics(
        _context(),
        metric="gross_gmv",
        start=date(2026, 9, 10),
        end=date(2026, 9, 23),
        now=WEDNESDAY,
    )
    assert result.data_cutoff == date(2026, 9, 23)
    assert result.source in {DataSource.REALTIME, DataSource.DAILY_ROLLUP, DataSource.MIXED}
    assert result.definition_version


# --- 混合边界不重不漏（由 SafeQueryService 保证；这里只测来源标注透传） -----------------


@pytest.mark.asyncio
async def test_source_label_reflects_underlying_tables() -> None:
    fake = FakeSafeQueryService(
        [_metric_result("gross_gmv", Decimal("500"), source_tables=("orders", "daily_rollup"))]
    )
    service = AttributionService(fake)
    result = await service.query_metrics(
        _context(),
        metric="gross_gmv",
        start=date(2026, 9, 10),
        end=date(2026, 9, 23),
        now=WEDNESDAY,
    )
    assert result.source == DataSource.MIXED


# --- 图表数据量上限（PRD §10.1） -----------------------------------------------------


def test_long_single_series_over_180_points_is_rejected_not_truncated() -> None:
    points = [Decimal(i) for i in range(181)]
    with pytest.raises(ChartPointLimitExceeded):
        AttributionService.enforce_chart_point_limits(series=[points])


def test_multi_series_total_points_capped_at_720() -> None:
    series = [[Decimal(1)] * 200 for _ in range(4)]  # 800 点合计，超过 720
    with pytest.raises(ChartPointLimitExceeded):
        AttributionService.enforce_chart_point_limits(series=series)


def test_series_within_limits_passes() -> None:
    AttributionService.enforce_chart_point_limits(series=[[Decimal(1)] * 180])
    AttributionService.enforce_chart_point_limits(series=[[Decimal(1)] * 180] * 4)


# --- 退款口径（O3）：net_gmv 由后端相减，不由模型算 -----------------------------------


@pytest.mark.asyncio
async def test_net_gmv_is_gross_gmv_minus_refund_amount_computed_by_backend() -> None:
    fake = FakeSafeQueryService(
        [
            _metric_result("gross_gmv", Decimal("10000")),
            _metric_result("refund_amount", Decimal("1500")),
        ]
    )
    service = AttributionService(fake)
    result = await service.query_metrics(
        _context(), metric="net_gmv", start=date(2026, 9, 10), end=date(2026, 9, 23), now=WEDNESDAY
    )
    assert result.value == Decimal("8500")
    # 两次真实查询都发生了（gross_gmv、refund_amount），减法在这里做，不是模型给出的数字。
    assert {call.metric for call in fake.calls} == {"gross_gmv", "refund_amount"}


@pytest.mark.asyncio
async def test_net_gmv_treats_missing_refunds_as_zero() -> None:
    gross = _metric_result("gross_gmv", Decimal("800"))
    refund = replace(_metric_result("refund_amount", Decimal("0")), rows=[{"refund_amount": None}])
    result = await AttributionService(FakeSafeQueryService([gross, refund])).query_metrics(
        _context(), metric="net_gmv", start=date(2026, 9, 21),
        end=date(2026, 9, 23), now=WEDNESDAY,
    )
    assert result.value == Decimal("800")


def test_refund_adjusted_value_never_labelled_gmv() -> None:
    """O3：退款冲减后的值不得继续称为 GMV，只有 net_gmv 例外。"""

    for code, spec in METRIC_SPECS.items():
        if code in ("refund_amount", "gross_gmv"):
            continue
        if "gmv" in code:
            assert code == "net_gmv" or "refund" not in spec.label, code


# --- 超出查询上限不静默截断 -----------------------------------------------------------


@pytest.mark.asyncio
async def test_unsupported_range_surfaces_explicit_limit_not_silent_truncation() -> None:
    class RaisingSafeQueryService:
        async def execute(self, context, intent, *, now, keywords=()):
            raise UnsupportedQueryError("超出可查询的时间范围上限")

    service = AttributionService(RaisingSafeQueryService())
    with pytest.raises(UnsupportedQueryError, match="超出"):
        await service.query_metrics(
            _context(),
            metric="gross_gmv",
            start=date(2000, 1, 1),
            end=date(2026, 9, 23),
            now=WEDNESDAY,
        )


# --- 图表可视化的时间序列查询（N3 阶段 C，2026-09-27 补做） ------------------------------


@pytest.mark.asyncio
async def test_query_metrics_series_returns_points_sorted_by_date() -> None:
    """每天一个数据点，按日期升序——图表需要的是序列，不是单个汇总值。"""

    fake = FakeSafeQueryService(
        [
            _date_series_result(
                "gross_gmv",
                [
                    (date(2026, 9, 22), Decimal("100")),
                    (date(2026, 9, 20), Decimal("300")),
                    (date(2026, 9, 21), Decimal("200")),
                ],
            )
        ]
    )
    service = AttributionService(fake)

    result = await service.query_metrics_series(
        _context(),
        metric="gross_gmv",
        start=date(2026, 9, 20),
        end=date(2026, 9, 22),
        now=WEDNESDAY,
    )

    assert [point.value for point in result.points] == [
        Decimal("300"),
        Decimal("200"),
        Decimal("100"),
    ]
    assert [point.date for point in result.points] == [
        date(2026, 9, 20),
        date(2026, 9, 21),
        date(2026, 9, 22),
    ]


@pytest.mark.asyncio
async def test_query_metrics_series_uses_date_dimension() -> None:
    """底层查询必须按 date 维度分组，不是标量聚合——这是与 query_metrics() 的关键区别。"""

    fake = FakeSafeQueryService(
        [_date_series_result("gross_gmv", [(date(2026, 9, 22), Decimal("1"))])]
    )
    service = AttributionService(fake)

    await service.query_metrics_series(
        _context(),
        metric="gross_gmv",
        start=date(2026, 9, 22),
        end=date(2026, 9, 22),
        now=WEDNESDAY,
    )

    assert fake.calls[0].dimensions == ["date"]


@pytest.mark.asyncio
async def test_query_metrics_series_computes_net_gmv_per_day() -> None:
    """net_gmv 序列也必须逐日相减，不能只对汇总值相减——否则每日趋势会算错。"""

    fake = FakeSafeQueryService(
        [
            _date_series_result(
                "gross_gmv",
                [(date(2026, 9, 20), Decimal("500")), (date(2026, 9, 21), Decimal("600"))],
            ),
            _date_series_result(
                "refund_amount",
                [(date(2026, 9, 20), Decimal("50")), (date(2026, 9, 21), Decimal("100"))],
            ),
        ]
    )
    service = AttributionService(fake)

    result = await service.query_metrics_series(
        _context(), metric="net_gmv", start=date(2026, 9, 20), end=date(2026, 9, 21), now=WEDNESDAY
    )

    assert [point.value for point in result.points] == [Decimal("450"), Decimal("500")]


@pytest.mark.asyncio
async def test_query_metrics_series_missing_day_is_zero_not_dropped() -> None:
    """某天没有任何符合条件的数据（0 单）时，图表仍要在该天显示一个点（值为 0），
    不能因为数据库那天没有行就让这一天在序列里消失——消失会让折线图断裂成误导性的形状。"""

    fake = FakeSafeQueryService(
        [_date_series_result("gross_gmv", [(date(2026, 9, 20), Decimal("100"))])]
    )
    service = AttributionService(fake)

    result = await service.query_metrics_series(
        _context(),
        metric="gross_gmv",
        start=date(2026, 9, 20),
        end=date(2026, 9, 21),
        now=WEDNESDAY,
    )

    assert [point.value for point in result.points] == [Decimal("100"), Decimal("0")]


@pytest.mark.asyncio
async def test_query_metrics_series_enforces_chart_point_limit() -> None:
    """超过单序列上限时明确拒绝，不静默截断（同 attribute_change 的既有规则）。"""

    too_many_days = MAX_SINGLE_SERIES_POINTS + 1
    service = AttributionService(FakeSafeQueryService([_date_series_result("gross_gmv", [])]))

    with pytest.raises(ChartPointLimitExceeded):
        await service.query_metrics_series(
            _context(),
            metric="gross_gmv",
            start=date(2026, 1, 1),
            end=date(2026, 1, 1) + timedelta(days=too_many_days - 1),
            now=WEDNESDAY,
        )
