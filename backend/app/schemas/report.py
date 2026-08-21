"""每日经营日报的独立 API 契约。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class DailyReportMetric(BaseModel):
    metric_code: str
    display_name: str
    unit: str
    value: Decimal | int


class DailyReportResponse(BaseModel):
    answer_id: UUID
    report_date: date
    metrics: list[DailyReportMetric] = Field(default_factory=list)
    suggestions: list[str] = Field(min_length=2, max_length=2)
    degraded: bool
    degraded_reason: str | None = None
