"""指标口径响应。"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.chat import MetricStatus


class MetricDefinitionResponse(BaseModel):
    metric_code: str
    display_name: str
    unit: str
    definition: str
    source: str
    owner: str
    status: MetricStatus
