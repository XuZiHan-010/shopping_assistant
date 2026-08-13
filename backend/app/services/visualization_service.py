"""从受控查询结果构造图表，不接受模型提供的字段名。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.metrics.catalog import MetricPayload
from app.schemas.chat import ChartType, Visualization
from app.services.safe_query import QueryResult


class VisualizationService:
    """只使用 QueryResult 已登记的维度列和指标列生成图表。"""

    def build(self, result: QueryResult, metric: MetricPayload | None) -> Visualization:
        if not result.rows or metric is None:
            return Visualization(enabled=False)

        metric_columns = {column.key for column in result.columns if column.kind == "METRIC"}
        dimensions = [column.key for column in result.columns if column.kind == "DIMENSION"]
        metric_key = _metric_key(metric, metric_columns)
        if metric_key is None or not dimensions:
            return Visualization(enabled=False)

        dimension_key = "date" if "date" in dimensions else dimensions[0]
        chart_type = ChartType.LINE if dimension_key == "date" else ChartType.BAR
        allowed_types = (
            [ChartType.LINE] if chart_type is ChartType.LINE else [ChartType.BAR, ChartType.PIE]
        )
        return Visualization(
            enabled=True,
            type=chart_type,
            allowed_types=allowed_types,
            title=f"{metric.display_name}趋势" if dimension_key == "date" else metric.display_name,
            dimension_key=dimension_key,
            metric_key=metric_key,
            unit=metric.unit,
            data=[
                {
                    dimension_key: _json_value(row.get(dimension_key)),
                    metric_key: _json_value(row.get(metric_key)),
                }
                for row in result.rows
            ],
        )


# 生成指标的数值列只能出自两套固定模板；模型给的展示名称与单位只用于**挑选**
# 其中一列，不能凭空造列。口径与参考项目 VisualizationService#generatedMetricValueField
# 一致：先按单位判定，单位不明确时按展示名称关键词判定，仍不明确时按订单/退款笔数兜底。
_GENERATED_METRIC_PREFERENCES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("元", ("gmv", "金额", "销售额", "成交额", "实付", "收入"), ("paid_amount", "refund_amount")),
    ("人", ("用户", "买家", "人数"), ("order_user_count", "refund_user_count")),
    ("件", ("销量", "销售量", "商品件数", "sku"), ("quantity",)),
)
# 关键词与单位都没命中时的稳定顺序，保证任何模板都能挑出一列可画的数值。
_GENERATED_METRIC_FALLBACK: tuple[str, ...] = (
    "order_count",
    "refund_count",
    "paid_amount",
    "refund_amount",
    "quantity",
    "order_user_count",
    "refund_user_count",
)


def _metric_key(metric: MetricPayload, columns: set[str]) -> str | None:
    if not metric.generated:
        return metric.metric_code if metric.metric_code in columns else None
    return _generated_metric_key(metric, columns)


def _generated_metric_key(metric: MetricPayload, columns: set[str]) -> str | None:
    name = metric.display_name.lower()
    for unit, keywords, candidates in _GENERATED_METRIC_PREFERENCES:
        if metric.unit != unit and not any(keyword in name for keyword in keywords):
            continue
        for key in candidates:
            if key in columns:
                return key
    for key in _GENERATED_METRIC_FALLBACK:
        if key in columns:
            return key
    return None


def _json_value(value: object | None) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, str | int | float):
        return value
    return str(value)
