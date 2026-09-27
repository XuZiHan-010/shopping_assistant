"""v2 图表可视化构造（N3 阶段 C，PRD M3，契约 §8.7.11）。

从 `AttributionService` 的确定性输出（`MetricSeriesResult`/`AttributionResult`）构造
`Visualization`——**模型不经手这份数据**：这里只是纯函数，接收已经算好的数字，
不做任何聚合或推断（R4）。图表类型选择规则与 v1 `visualization_service.py` 一致
（时间维度默认折线图、只允许折线图；分类维度默认柱状图、允许柱状图或饼图），
但输入形状不同（v2 归因结果不是 v1 的 `QueryResult`），因此单独实现，不强行适配
v1 的函数签名——v1/v2 不互相 import 业务逻辑（§5.6），只共用 `Visualization`/`ChartType`
这两个类型定义（与 `AnalysisSource`/`QualityStatus` 同一先例）。
"""

from __future__ import annotations

from app.analytics.contract import METRIC_SPECS
from app.schemas.chat import ChartType, Visualization
from app.services.v2.attribution import AttributionResult, MetricSeriesResult

#: `net_gmv` 不在 `METRIC_SPECS` 里（它是查询层之上用两次单表聚合相减得出的，
#: 不是单表可聚合的指标，见 `attribution.py` 的说明）；展示名/单位借用 `gross_gmv`
#: 的——两者单位一致（都是"元"），且 `net_gmv` 的字面意思就是"扣掉退款后的毛额"。
_DISPLAY_METRIC_FALLBACK = {"net_gmv": "gross_gmv"}


def _display_metadata(metric: str) -> tuple[str, str]:
    """返回 `(展示名, 单位)`；未注册的指标退回 `(metric, "")`，不臆造。"""

    spec_code = _DISPLAY_METRIC_FALLBACK.get(metric, metric)
    spec = METRIC_SPECS.get(spec_code)
    return (spec.label, spec.unit) if spec is not None else (metric, "")


def build_visualization_for_series(result: MetricSeriesResult, *, metric: str) -> Visualization:
    """时间序列（`query_metrics_series`）只画折线图——趋势数据没有其他合理呈现方式。"""

    if not result.points:
        return Visualization(enabled=False)
    display_name, unit = _display_metadata(metric)
    return Visualization(
        enabled=True,
        type=ChartType.LINE,
        allowed_types=[ChartType.LINE],
        title=f"{display_name}趋势",
        dimension_key="date",
        metric_key=metric,
        unit=unit,
        data=[
            {"date": point.date.isoformat(), metric: str(point.value)}
            for point in result.points
        ],
    )


def build_visualization_for_attribution(
    result: AttributionResult, *, metric: str
) -> Visualization:
    """分类构成（`attribute_change`）默认柱状图，允许切换到饼图；归因停止时不画图。"""

    if result.stopped or not result.segments:
        return Visualization(enabled=False)
    display_name, unit = _display_metadata(metric)
    return Visualization(
        enabled=True,
        type=ChartType.BAR,
        allowed_types=[ChartType.BAR, ChartType.PIE],
        title=display_name,
        dimension_key="category",
        metric_key=metric,
        unit=unit,
        data=[
            {"category": segment.name, metric: str(segment.absolute_contribution)}
            for segment in result.segments
        ],
    )
