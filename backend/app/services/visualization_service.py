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
        if metric.metric_code not in metric_columns or not dimensions:
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
            metric_key=metric.metric_code,
            unit=metric.unit,
            data=[
                {
                    dimension_key: _json_value(row.get(dimension_key)),
                    metric.metric_code: _json_value(row.get(metric.metric_code)),
                }
                for row in result.rows
            ],
        )


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
