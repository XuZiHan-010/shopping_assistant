"""指标口径响应。"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.chat import MetricDefinitionSource, MetricStatus


class MetricDefinitionResponse(BaseModel):
    metric_code: str
    display_name: str
    unit: str
    definition: str
    sql_definition: str
    dimensions: list[str]
    source_database: str
    source_table: str
    report_url: str | None
    source: MetricDefinitionSource
    generated: bool
    notice: str | None
    owner: str
    status: MetricStatus
