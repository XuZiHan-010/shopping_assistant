"""首页经营主指标（W 阶段 Task 2，PRD M1/M3，契约 §8.12.4）。

本模块只做**组合**：主指标序列、类目归因与辅助指标全部来自 `AttributionService`
（与商家助手的 `query_metrics` / `attribute_change` 工具同一实现），周期来自同一个
`comparison_periods()`。本模块自己只负责：

- 元 → 整数分、[0,1] 小数 → 万分比的 Decimal 换算（`ROUND_HALF_UP`，不经过 float）；
- 归因 Top 5 + 「其余 N 个类目」合计，不静默截断；
- 分项失败时取空值并如实披露降级（R7），绝不回退到示意数字。

全程不构造、不调用任何 LLM 客户端（R3/R4）。

**基期为空（`baseline_cents=None`）的语义**（§8.12.4 把判定留给服务层）：
「基期有可比数据」只按一条规则判定——`attribute_change` 成功且未因基期数据缺口停止
（即基期存在任何订单或退款行）。因此：

1. 基期确实没有数据（新店）：`baseline_cents=None`、`baseline_series=[]`、
   归因 `STOPPED`（给出数据缺口原因），**不算降级**——这是事实，不是故障；
2. 基期序列查询失败：基期取空值，整体降级；
3. 归因查询失败：无法确认基期是否可比，基期同样取空值（不以 0 冒充），整体降级；
4. 只有本期主指标失败时整体返回 503：`current_cents` 不可空，没有诚实的降级表示。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from sqlalchemy.exc import SQLAlchemyError

from app.analytics.dates import business_today
from app.core.errors import DatabaseUnavailableError
from app.core.security import MerchantContext
from app.localization.locales import SupportedLocale
from app.schemas.chat import AnalysisSource, QualityStatus
from app.schemas.v2.common import AnalysisSourceEntry
from app.schemas.v2.merchant_ops import (
    MAX_ATTRIBUTION_SEGMENTS,
    MAX_RATIO_BP,
    MerchantMetricsOverviewResponse,
    MerchantMetricsOverviewSource,
    OverviewAttribution,
    OverviewAttributionMode,
    OverviewAttributionSegment,
    OverviewHeadline,
    OverviewMetricPoint,
    OverviewPeriod,
    OverviewSecondaryMetric,
    OverviewSecondaryMetricCode,
    OverviewSecondaryUnit,
)
from app.services.safe_query import UnsupportedQueryError
from app.services.v2.attribution import (
    AttributionResult,
    AttributionService,
    ChartPointLimitExceeded,
    ComparisonPeriods,
    DataSource,
    MetricSeriesResult,
    comparison_periods,
)

logger = logging.getLogger(__name__)

#: 每个分项在独立的数据库会话里执行：一个分项的 SQL 失败会让该会话的事务作废，
#: 共用会话会把一次局部失败放大成所有后续分项一起失败。
OverviewScope = Callable[[], AbstractAsyncContextManager[AttributionService]]

HEADLINE_METRIC: Final = "net_gmv"
ATTRIBUTION_DIMENSION: Final = "category"

#: 分项可降级的失败类型。`SafeQueryService` 已把 SQLAlchemyError 转成
#: UnsupportedQueryError，这里仍兜住原始 SQLAlchemyError 以防仓储层直接抛出。
_SUBITEM_ERRORS: Final = (UnsupportedQueryError, ChartPointLimitExceeded, SQLAlchemyError)

_SECONDARY: Final[tuple[tuple[OverviewSecondaryMetricCode, OverviewSecondaryUnit], ...]] = (
    ("order_count", OverviewSecondaryUnit.COUNT),
    ("refund_amount", OverviewSecondaryUnit.CENTS),
    ("return_rate", OverviewSecondaryUnit.RATIO_BP),
)

_ITEM_NAMES: Final[dict[str, dict[SupportedLocale, str]]] = {
    "baseline": {SupportedLocale.ZH_CN: "基期对比", SupportedLocale.EN_US: "baseline comparison"},
    "attribution": {
        SupportedLocale.ZH_CN: "类目归因",
        SupportedLocale.EN_US: "category attribution",
    },
    "order_count": {SupportedLocale.ZH_CN: "订单量", SupportedLocale.EN_US: "order count"},
    "refund_amount": {SupportedLocale.ZH_CN: "退款金额", SupportedLocale.EN_US: "refund amount"},
    "return_rate": {SupportedLocale.ZH_CN: "退货率", SupportedLocale.EN_US: "return rate"},
}

_DEGRADED_REASON: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: "部分指标暂时无法查询，已留空：{items}",
    SupportedLocale.EN_US: "Some metrics are temporarily unavailable and left blank: {items}",
}

_STOPPED_BASELINE_GAP: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: "基期数据缺口：所选基期没有可比数据，归因已停止",
    SupportedLocale.EN_US: (
        "Baseline gap: the comparison period has no comparable data, so attribution stopped"
    ),
}
_STOPPED_FAILED: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: "类目归因暂时无法查询，已停止归因",
    SupportedLocale.EN_US: "Category attribution is temporarily unavailable, so it stopped",
}
_STOPPED_MISMATCH: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: "类目合计与整体净成交额无法对齐，已停止归因以免给出错误贡献",
    SupportedLocale.EN_US: (
        "Category totals do not reconcile with overall net GMV, so attribution stopped"
    ),
}


def ratio_to_bp(raw: Decimal | None) -> int | None:
    """注册表比例（[0,1] 小数，未预乘 100）→ 万分比整数；无数据保持 None，不写成 0。"""

    if raw is None:
        return None
    if not isinstance(raw, Decimal):
        raise TypeError("比例必须为 Decimal，禁止经过 float 换算")
    return int((raw * 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _signed_cents(yuan: Decimal) -> int:
    """元 → 整数分；净成交额与贡献值可为负，不能用只接受非负的 `yuan_to_cents`。"""

    return int((yuan * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _change_ratio_bp(current: int, baseline: int | None) -> int | None:
    """基期为空或非正时不给比例（契约）；超出契约范围同样给 null，不产生伪精确比例。"""

    if baseline is None or baseline <= 0:
        return None
    ratio = (Decimal(current - baseline) * 10000 / Decimal(baseline)).quantize(
        Decimal(1), rounding=ROUND_HALF_UP
    )
    value = int(ratio)
    return value if abs(value) <= MAX_RATIO_BP else None


def _period_labels(periods: ComparisonPeriods, locale: SupportedLocale) -> tuple[str, str]:
    """与 `AttributionService` 的 `comparison_label` 同义；中文直接复用原文。"""

    if locale is SupportedLocale.ZH_CN:
        return periods.comparison_label
    span = periods.span_days
    if span == 1:
        return "First day this week", "First day last week"
    current = "This period" if span >= 7 else f"First {span} days this week"
    return current, f"First {span} days last week"


def _points(series: MetricSeriesResult) -> list[OverviewMetricPoint]:
    return [
        OverviewMetricPoint(date=point.date, value_cents=_signed_cents(point.value))
        for point in series.points
    ]


def _stopped(reason: str) -> OverviewAttribution:
    return OverviewAttribution(
        mode=OverviewAttributionMode.STOPPED,
        segments=[],
        remaining_count=0,
        remaining_contribution_cents=0,
        stopped_reason=reason,
    )


def _attribution(
    result: AttributionResult,
    *,
    current_cents: int,
    baseline_cents: int | None,
) -> OverviewAttribution | None:
    """把归因结果换成契约形状；类目合计对不上主指标时返回 None（由调用方降级）。"""

    rows = [
        (
            segment,
            _signed_cents(segment.current_value),
            _signed_cents(segment.baseline_value),
        )
        for segment in result.segments
    ]
    # 恒等式的前提是「类目合计 = 主指标」。整单金额与订单项金额在历史数据里可能不一致，
    # 此时硬凑 remaining 会伪造贡献，宁可停止归因并如实降级。
    if sum(cur for _, cur, _ in rows) != current_cents:
        return None
    if baseline_cents is not None and sum(base for _, _, base in rows) != baseline_cents:
        return None

    mode = OverviewAttributionMode(result.mode)
    shares: list[int | None] = [None] * len(rows)
    if mode is OverviewAttributionMode.SHARE:
        shares = [ratio_to_bp(segment.share) for segment, _, _ in rows]
        # 正负大幅抵消时占比可达上百倍，超出契约范围就改报绝对贡献值（D19 降级思路）。
        if any(share is None or abs(share) > MAX_RATIO_BP for share in shares):
            mode = OverviewAttributionMode.ABSOLUTE_CONTRIBUTION
            shares = [None] * len(rows)

    segments = [
        OverviewAttributionSegment(
            name=segment.name,
            current_cents=cur,
            baseline_cents=base,
            contribution_cents=cur - base,
            share_bp=share,
        )
        for (segment, cur, base), share in zip(rows, shares, strict=True)
    ]
    segments.sort(key=lambda item: (-abs(item.contribution_cents), item.name))
    shown, rest = segments[:MAX_ATTRIBUTION_SEGMENTS], segments[MAX_ATTRIBUTION_SEGMENTS:]
    return OverviewAttribution(
        mode=mode,
        segments=shown,
        remaining_count=len(rest),
        remaining_contribution_cents=sum(item.contribution_cents for item in rest),
        stopped_reason=None,
    )


def _secondary_value(code: OverviewSecondaryMetricCode, value: Decimal | None) -> int | None:
    if value is None:
        return None
    if code == "order_count":
        return int(value)
    if code == "refund_amount":
        return _signed_cents(value)
    return ratio_to_bp(value)


def _combined_source(sources: list[DataSource]) -> MerchantMetricsOverviewSource:
    distinct = set(sources)
    if len(distinct) == 1:
        return MerchantMetricsOverviewSource(distinct.pop().value)
    return MerchantMetricsOverviewSource.MIXED


async def build_metrics_overview(
    scope: OverviewScope,
    merchant: MerchantContext,
    *,
    now: datetime,
    business_timezone: str,
    locale: SupportedLocale,
) -> MerchantMetricsOverviewResponse:
    periods = comparison_periods(business_today(now, timezone=business_timezone))
    current_range, baseline_range = periods.current, periods.baseline
    failed: list[str] = []
    sources: list[DataSource] = []

    # 1. 本期主指标序列：唯一不可降级的分项。
    try:
        async with scope() as service:
            current = await service.query_metrics_series(
                merchant,
                metric=HEADLINE_METRIC,
                start=current_range.start,
                end=current_range.end,
                now=now,
            )
    except _SUBITEM_ERRORS as error:
        logger.warning("metrics overview current headline failed: %s", type(error).__name__)
        raise DatabaseUnavailableError from error
    sources.append(current.source)
    current_series = _points(current)
    current_cents = sum(point.value_cents for point in current_series)

    # 2. 基期主指标序列。
    baseline_series: list[OverviewMetricPoint] | None = None
    try:
        async with scope() as service:
            baseline = await service.query_metrics_series(
                merchant,
                metric=HEADLINE_METRIC,
                start=baseline_range.start,
                end=baseline_range.end,
                now=now,
            )
        sources.append(baseline.source)
        baseline_series = _points(baseline)
    except _SUBITEM_ERRORS as error:
        logger.warning("metrics overview baseline failed: %s", type(error).__name__)
        failed.append("baseline")

    # 3. 类目归因（与 attribute_change 工具同一实现、同一周期）。
    attribution_result: AttributionResult | None = None
    try:
        async with scope() as service:
            attribution_result = await service.attribute_change(
                merchant,
                metric=HEADLINE_METRIC,
                dimension=ATTRIBUTION_DIMENSION,
                now=now,
                business_timezone=business_timezone,
            )
        sources.append(attribution_result.source)
    except _SUBITEM_ERRORS as error:
        logger.warning("metrics overview attribution failed: %s", type(error).__name__)
        failed.append("attribution")

    baseline_comparable = (
        baseline_series is not None
        and attribution_result is not None
        and not attribution_result.stopped
    )
    if not baseline_comparable:
        baseline_series = None
    baseline_cents = (
        sum(point.value_cents for point in baseline_series) if baseline_series is not None else None
    )

    if attribution_result is None:
        attribution = _stopped(_STOPPED_FAILED[locale])
    elif attribution_result.stopped:
        attribution = _stopped(_STOPPED_BASELINE_GAP[locale])
    else:
        built = _attribution(
            attribution_result,
            current_cents=current_cents,
            baseline_cents=baseline_cents,
        )
        if built is None:
            logger.warning("metrics overview attribution does not reconcile with headline")
            failed.append("attribution")
            attribution = _stopped(_STOPPED_MISMATCH[locale])
        else:
            attribution = built

    # 4. 辅助指标：各自独立降级。
    secondary: list[OverviewSecondaryMetric] = []
    for code, unit in _SECONDARY:
        current_value: int | None = None
        baseline_value: int | None = None
        try:
            async with scope() as service:
                current_metric = await service.query_metrics(
                    merchant, metric=code, start=current_range.start, end=current_range.end,
                    now=now,
                )
                baseline_metric = await service.query_metrics(
                    merchant, metric=code, start=baseline_range.start, end=baseline_range.end,
                    now=now,
                )
            sources.extend((current_metric.source, baseline_metric.source))
            current_value = _secondary_value(code, current_metric.value)
            baseline_value = _secondary_value(code, baseline_metric.value)
        except _SUBITEM_ERRORS as error:
            logger.warning("metrics overview %s failed: %s", code, type(error).__name__)
            failed.append(code)
        secondary.append(
            OverviewSecondaryMetric(
                metric_code=code,
                unit=unit,
                current_value=current_value,
                baseline_value=baseline_value,
            )
        )

    degraded = bool(failed)
    degraded_reason = (
        _DEGRADED_REASON[locale].format(
            items=("、" if locale is SupportedLocale.ZH_CN else ", ").join(
                _ITEM_NAMES[item][locale] for item in dict.fromkeys(failed)
            )
        )
        if degraded
        else None
    )
    current_label, baseline_label = _period_labels(periods, locale)

    return MerchantMetricsOverviewResponse(
        analysis_sources=[
            AnalysisSourceEntry(
                source=AnalysisSource.DATABASE,
                degraded=degraded,
                degraded_reason=degraded_reason,
            )
        ],
        quality_status=QualityStatus.NOT_RUN,
        quality_attempts=0,
        quality_notes=[],
        degraded=degraded,
        degraded_reason=degraded_reason,
        business_timezone=business_timezone,
        data_as_of=now,
        source=_combined_source(sources),
        definition_version=current.definition_version,
        current_period=OverviewPeriod(
            start=current_range.start, end=current_range.end, label=current_label
        ),
        baseline_period=OverviewPeriod(
            start=baseline_range.start, end=baseline_range.end, label=baseline_label
        ),
        headline=OverviewHeadline(
            current_cents=current_cents,
            baseline_cents=baseline_cents,
            change_ratio_bp=_change_ratio_bp(current_cents, baseline_cents),
            current_series=current_series,
            baseline_series=baseline_series or [],
        ),
        attribution=attribution,
        secondary=secondary,
    )
