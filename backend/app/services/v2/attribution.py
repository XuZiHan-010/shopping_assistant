"""业绩洞察与归因（N3 阶段 C Task 1，PRD M3、D19、S5）。

复用 v1 `SafeQueryService` 做实际的受控查询与聚合，本模块只负责 D19 明确要求、
v1 尚未实现的确定性业务规则：等长可比周期、绝对贡献值降级、图表数据点上限、
以及 `net_gmv = gross_gmv - refund_amount` 的后端减法（O3）。

**模型不写 SQL、不选数据源、不定指标公式、不产生图表数据点**（R4）：
本模块的每个公开方法只接收结构化参数，返回结构化结果；归因用的两次查询、
两数相减、占比计算全部是本模块内的确定性代码，不经过任何 LLM 调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.analytics.contract import metric_spec
from app.analytics.dates import business_today
from app.core.security import MerchantContext
from app.intent.models import ComparisonMode, DateRange, QueryIntent
from app.metrics.caliber import METRIC_CALIBER_VERSION
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services.safe_query import QueryResult

#: PRD §10.1：单序列最多 180 点，多序列合计最多 720 点；超出由后端聚合（如按周），
#: 不由前端或模型截断——这里只负责拒绝超限输入，聚合本身在查询层完成。
MAX_SINGLE_SERIES_POINTS = 180
MAX_TOTAL_SERIES_POINTS = 720

#: 整体变化幅度低于这个比例时视为"接近零"，改报绝对贡献值而非占比（D19）。
_NEAR_ZERO_THRESHOLD = Decimal("0.05")

#: 归因用的默认下钻维度到查询维度码的映射；目前只开放 category，
#: 与 v1 `DIMENSION_SPECS` 保持一致（`app/analytics/contract.py`）。
_ATTRIBUTION_DIMENSION = "category"


class ChartPointLimitExceeded(ValueError):
    """图表数据点超出 PRD §10.1 上限；调用方必须改用后端聚合的粗粒度，不静默截断。"""


class DataSource(StrEnum):
    REALTIME = "REALTIME"
    DAILY_ROLLUP = "DAILY_ROLLUP"
    MIXED = "MIXED"


class SafeQueryLike(Protocol):
    async def execute(
        self,
        context: MerchantContext,
        intent: QueryIntent,
        *,
        now: datetime,
        keywords: tuple[str, ...] = (),
    ) -> QueryResult: ...


@dataclass(frozen=True)
class MetricSeriesPoint:
    date: date
    value: Decimal


@dataclass(frozen=True)
class MetricSeriesResult:
    """`query_metrics_series` 的输出：图表可视化需要的是逐日序列，不是单个汇总值。"""

    points: tuple[MetricSeriesPoint, ...]
    data_cutoff: date
    source: DataSource
    definition_version: str


@dataclass(frozen=True)
class MetricQueryResult:
    """`query_metrics` 的输出：响应必带数据截至时间、来源、指标定义版本（D19）。"""

    value: Decimal | None
    series: tuple[Decimal, ...]
    data_cutoff: date
    source: DataSource
    definition_version: str
    aggregated_to: str | None = None


@dataclass(frozen=True)
class Segment:
    name: str
    current_value: Decimal
    baseline_value: Decimal
    #: 整体变化明显时给出占比；接近零或正负抵消时为 None（D19 降级）。
    share: Decimal | None
    #: 恒有值：即使给了占比，也保留绝对贡献值供展示。
    absolute_contribution: Decimal


@dataclass(frozen=True)
class AttributionResult:
    mode: str  # "SHARE" | "ABSOLUTE_CONTRIBUTION"
    segments: tuple[Segment, ...]
    comparison_label: tuple[str, str]
    stopped: bool
    data_cutoff: date
    source: DataSource
    definition_version: str
    stopped_reason: str | None = None


def _source_from_tables(source_tables: tuple[str, ...]) -> DataSource:
    has_rollup = any("rollup" in table for table in source_tables)
    has_realtime = any("rollup" not in table for table in source_tables)
    if has_rollup and has_realtime:
        return DataSource.MIXED
    if has_rollup:
        return DataSource.DAILY_ROLLUP
    return DataSource.REALTIME


def _definition_version(metric: str) -> str:
    """指标定义版本：目前用指标契约里固定的口径标签（O3 退款口径的三个指标共享同一版本）。

    等正式指标资产接入版本号字段（Task 6 `get_metric_definition`）后，
    两处应改为读同一个来源，不在两个模块里各自维护版本字符串。
    """

    del metric
    return METRIC_CALIBER_VERSION


def _equal_length_baseline(current: DateRange, *, today: date) -> tuple[DateRange, str, str]:
    """本周（或本月）未过完时，先试与基期同样长度的可比周期，而不是整周/整月对比。"""

    span = (min(current.end, today) - current.start).days + 1
    baseline_start = current.start - timedelta(days=7)
    baseline_end = baseline_start + timedelta(days=span - 1)
    baseline = DateRange(start=baseline_start, end=baseline_end)
    return baseline, f"本周前 {span} 天" if span < 7 else "本周期", f"上周前 {span} 天"


@dataclass(frozen=True)
class ComparisonPeriods:
    """归因与首页主指标共用的对比周期：本周一至今天 vs. 上周等长区间（D19、§8.12.4）。"""

    current: DateRange
    baseline: DateRange
    #: 与本期、基期一一对应的中文说明，如 ("本周前 3 天", "上周前 3 天")。
    comparison_label: tuple[str, str]

    @property
    def span_days(self) -> int:
        return (self.current.end - self.current.start).days + 1


def comparison_periods(today: date) -> ComparisonPeriods:
    """周期计算的唯一实现：`attribute_change` 与首页指标总览都从这里取，不另写一套。

    `today` 必须是业务时区下的日期（调用方负责换算）。
    """

    week_start = today - timedelta(days=today.weekday())
    current_range = DateRange(start=week_start, end=today)
    baseline_range, current_label, baseline_label = _equal_length_baseline(
        current_range, today=today
    )
    return ComparisonPeriods(
        current=current_range,
        baseline=baseline_range,
        comparison_label=(current_label, baseline_label),
    )


def _intent_for_segment(metric: str, *, date_range: DateRange, dimension: str) -> QueryIntent:
    return QueryIntent(
        answer_mode=AnswerMode.METRIC,
        category=QuestionCategory.TRADE,
        metric=metric,
        dimensions=[dimension],
        date_range=date_range,
        comparison=ComparisonMode.NONE,
    )


def _intent_for_scalar(metric: str, *, date_range: DateRange) -> QueryIntent:
    return QueryIntent(
        answer_mode=AnswerMode.METRIC,
        category=QuestionCategory.TRADE,
        metric=metric,
        date_range=date_range,
        comparison=ComparisonMode.NONE,
    )


def _rows_by_dimension(result: QueryResult, *, dimension: str, metric: str) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    for row in result.rows:
        key = str(row[dimension])
        raw = row[metric]
        values[key] = Decimal(str(raw)) if raw is not None else Decimal("0")
    return values


def _rows_by_date(result: QueryResult, *, metric: str) -> dict[date, Decimal]:
    values: dict[date, Decimal] = {}
    for row in result.rows:
        raw_date = row["date"]
        day = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
        raw_value = row[metric]
        values[day] = Decimal(str(raw_value)) if raw_value is not None else Decimal("0")
    return values


def _dates_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


class AttributionService:
    def __init__(self, query_service: SafeQueryLike) -> None:
        self._query_service = query_service

    @staticmethod
    def enforce_chart_point_limits(*, series: list[list[Decimal]]) -> None:
        for points in series:
            if len(points) > MAX_SINGLE_SERIES_POINTS:
                raise ChartPointLimitExceeded(
                    f"单序列 {len(points)} 个数据点超过上限 {MAX_SINGLE_SERIES_POINTS}，"
                    "请改用更粗粒度（如按周）"
                )
        total = sum(len(points) for points in series)
        if total > MAX_TOTAL_SERIES_POINTS:
            raise ChartPointLimitExceeded(
                f"多序列合计 {total} 个数据点超过上限 {MAX_TOTAL_SERIES_POINTS}，"
                "请改用更粗粒度（如按周）"
            )

    async def query_metrics(
        self,
        context: MerchantContext,
        *,
        metric: str,
        start: date,
        end: date,
        now: datetime,
    ) -> MetricQueryResult:
        """单指标查询；`net_gmv` 由 `gross_gmv - refund_amount` 两次真实查询相减得出（O3）。

        `now` 必须由调用方（工具层）传入当前时刻，本方法不取系统时钟——与
        `SafeQueryService.execute()` 的既有约定一致，保证「现在」只有一个来源。
        """

        date_range = DateRange(start=start, end=end)

        if metric == "net_gmv":
            gross = await self._scalar(context, "gross_gmv", date_range, now)
            refund = await self._scalar(context, "refund_amount", date_range, now)
            value = (gross.value or Decimal("0")) - (refund.value or Decimal("0"))
            source = DataSource.MIXED if gross.source != refund.source else gross.source
            return MetricQueryResult(
                value=value,
                series=(value,) if value is not None else (),
                data_cutoff=max(gross.data_cutoff, refund.data_cutoff),
                source=source,
                definition_version=_definition_version(metric),
            )

        metric_spec(metric)  # 未注册指标在这里就地拒绝，报文与 v1 一致
        result = await self._scalar(context, metric, date_range, now)
        return result

    async def query_metrics_series(
        self,
        context: MerchantContext,
        *,
        metric: str,
        start: date,
        end: date,
        now: datetime,
    ) -> MetricSeriesResult:
        """按天返回一段时间内的数值序列，供图表可视化使用（PRD M3：图表数据点由后端生成）。

        与 `query_metrics()` 的区别：那个方法算的是整段范围的**一个**汇总值；这里按
        `date` 维度分组，返回范围内**每一天**一个数据点——数据库没有任何行的那天
        补 0，不能让那一天从序列里消失（消失会让折线图断裂成误导性的形状）。
        """

        self._reject_oversized_range(start, end)
        date_range = DateRange(start=start, end=end)

        if metric == "net_gmv":
            gross = await self._series(context, "gross_gmv", date_range, now)
            refund = await self._series(context, "refund_amount", date_range, now)
            refund_by_date = {point.date: point.value for point in refund.points}
            points = tuple(
                MetricSeriesPoint(
                    date=point.date,
                    value=point.value - refund_by_date.get(point.date, Decimal("0")),
                )
                for point in gross.points
            )
            source = DataSource.MIXED if gross.source != refund.source else gross.source
            return MetricSeriesResult(
                points=points,
                data_cutoff=max(gross.data_cutoff, refund.data_cutoff),
                source=source,
                definition_version=_definition_version(metric),
            )

        metric_spec(metric)  # 未注册指标在这里就地拒绝，报文与 v1 一致
        return await self._series(context, metric, date_range, now)

    @staticmethod
    def _reject_oversized_range(start: date, end: date) -> None:
        days = (end - start).days + 1
        if days > MAX_SINGLE_SERIES_POINTS:
            raise ChartPointLimitExceeded(
                f"{days} 天超过单序列上限 {MAX_SINGLE_SERIES_POINTS} 个数据点，"
                "请改用更粗粒度（如按周）"
            )

    async def _series(
        self, context: MerchantContext, metric: str, date_range: DateRange, now: datetime
    ) -> MetricSeriesResult:
        intent = _intent_for_segment(metric, date_range=date_range, dimension="date")
        result = await self._query_service.execute(context, intent, now=now)
        values_by_date = _rows_by_date(result, metric=metric)
        points = tuple(
            MetricSeriesPoint(date=day, value=values_by_date.get(day, Decimal("0")))
            for day in _dates_between(date_range.start, date_range.end)
        )
        return MetricSeriesResult(
            points=points,
            data_cutoff=date_range.end,
            source=_source_from_tables(result.source_tables),
            definition_version=_definition_version(metric),
        )

    async def _scalar(
        self, context: MerchantContext, metric: str, date_range: DateRange, now: datetime
    ) -> MetricQueryResult:
        intent = _intent_for_scalar(metric, date_range=date_range)
        result = await self._query_service.execute(context, intent, now=now)
        value = None
        if result.rows:
            raw = result.rows[0].get(metric)
            value = Decimal(str(raw)) if raw is not None else None
        return MetricQueryResult(
            value=value,
            series=(value,) if value is not None else (),
            data_cutoff=date_range.end,
            source=_source_from_tables(result.source_tables),
            definition_version=_definition_version(metric),
        )

    async def attribute_change(
        self,
        context: MerchantContext,
        *,
        metric: str,
        dimension: str = _ATTRIBUTION_DIMENSION,
        now: datetime,
        business_timezone: str,
    ) -> AttributionResult:
        """五步归因中的确定性部分：定位贡献最大的细分、按幅度选择占比或绝对贡献值。

        模型只负责组织语言；本方法产出的数字是唯一允许被引用的归因结论。

        「今天」在这里按业务时区换算，调用方只传当前时刻：上海 00:00–08:00 时
        UTC 仍是前一天，由调用方各自取日期曾让助手工具与首页落在不同周期。
        """

        if now.tzinfo is None:
            raise ValueError("now 必须带时区，否则无法换算业务日")
        today_date = business_today(now, timezone=business_timezone)
        # 本周（周一起算）到目前为止的天数，用作等长基期的窗口长度。
        periods = comparison_periods(today_date)
        current_range, baseline_range = periods.current, periods.baseline
        current_label, baseline_label = periods.comparison_label

        current_values, current_source = await self._segment_values(
            context, metric=metric, date_range=current_range, dimension=dimension, now=now
        )
        baseline_values, baseline_source = await self._segment_values(
            context, metric=metric, date_range=baseline_range, dimension=dimension, now=now
        )
        source = (
            current_source if current_source == baseline_source else DataSource.MIXED
        )

        if not baseline_values:
            return AttributionResult(
                mode="ABSOLUTE_CONTRIBUTION",
                segments=(),
                comparison_label=(current_label, baseline_label),
                stopped=True,
                data_cutoff=today_date,
                source=source,
                definition_version=_definition_version(metric),
                stopped_reason="基期数据缺口：所选基期没有可比数据，归因已停止",
            )

        names = sorted(set(current_values) | set(baseline_values))
        total_current = sum(
            (current_values.get(name, Decimal("0")) for name in names), start=Decimal("0")
        )
        total_baseline = sum(
            (baseline_values.get(name, Decimal("0")) for name in names), start=Decimal("0")
        )
        total_change = total_current - total_baseline

        use_absolute = (
            total_baseline == 0 or abs(total_change) <= abs(total_baseline) * _NEAR_ZERO_THRESHOLD
        )

        segments = []
        for name in names:
            cur = current_values.get(name, Decimal("0"))
            base = baseline_values.get(name, Decimal("0"))
            contribution = cur - base
            share = None
            if not use_absolute and total_change != 0:
                share = (contribution / total_change).quantize(Decimal("0.001"))
            segments.append(
                Segment(
                    name=name,
                    current_value=cur,
                    baseline_value=base,
                    share=share,
                    absolute_contribution=contribution,
                )
            )
        segments.sort(key=lambda segment: abs(segment.absolute_contribution), reverse=True)

        return AttributionResult(
            mode="ABSOLUTE_CONTRIBUTION" if use_absolute else "SHARE",
            segments=tuple(segments),
            comparison_label=(current_label, baseline_label),
            stopped=False,
            data_cutoff=today_date,
            source=source,
            definition_version=_definition_version(metric),
        )

    async def _segment_values(
        self,
        context: MerchantContext,
        *,
        metric: str,
        date_range: DateRange,
        dimension: str,
        now: datetime,
    ) -> tuple[dict[str, Decimal], DataSource]:
        if metric == "net_gmv":
            gross, gross_source = await self._segment_values(
                context, metric="gross_gmv", date_range=date_range, dimension=dimension, now=now
            )
            refund, refund_source = await self._segment_values(
                context,
                metric="refund_amount",
                date_range=date_range,
                dimension=dimension,
                now=now,
            )
            values = {
                name: gross.get(name, Decimal("0")) - refund.get(name, Decimal("0"))
                for name in gross.keys() | refund.keys()
            }
            source = gross_source if gross_source == refund_source else DataSource.MIXED
            return values, source
        metric_spec(metric)
        intent = _intent_for_segment(metric, date_range=date_range, dimension=dimension)
        result = await self._query_service.execute(context, intent, now=now)
        if result.truncated:
            raise ChartPointLimitExceeded(
                "归因类目数量超过受控查询上限，请缩小日期范围或分析对象后重试"
            )
        return _rows_by_dimension(result, dimension=dimension, metric=metric), _source_from_tables(
            result.source_tables
        )
