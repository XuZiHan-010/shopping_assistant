"""每日经营日报的独立 API 契约。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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


class DailyReportRecomputeRequest(BaseModel):
    """管理员重算指定业务日日报的受控请求。"""

    merchant_id: UUID
    report_date: date
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason 不能为空")
        return normalized
