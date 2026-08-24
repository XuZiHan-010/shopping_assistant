"""Chat BI 看板的 API 契约。

比率为 ``null`` 时表示样本不足；这与实际的 0% 不同，前端必须明确区分。
"""

from __future__ import annotations

from datetime import date
from typing import Self

from pydantic import BaseModel, Field, model_validator

MAX_WINDOW_DAYS = 180


class ChatBiWindow(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date 不得晚于 end_date")
        if (self.end_date - self.start_date).days + 1 > MAX_WINDOW_DAYS:
            raise ValueError(f"查询窗口不得超过 {MAX_WINDOW_DAYS} 天")
        return self


class NorthStarPayload(BaseModel):
    """六项北极星指标，``None`` 表示样本不足。"""

    adoption_rate: float | None
    user_accuracy_rate: float | None
    system_accuracy_rate: float | None
    avg_thinking_ms: float | None
    hit_rate: float | None
    failure_rate: float | None


class ChatBiDailyPoint(NorthStarPayload):
    stat_date: date
    answer_total: int = Field(ge=0)


class ChatBiOverviewResponse(NorthStarPayload):
    start_date: date
    end_date: date
    answer_total: int = Field(ge=0)
    business_question_total: int = Field(ge=0)
    feedback_total: int = Field(ge=0)
    thinking_sample_count: int = Field(ge=0)
    daily: list[ChatBiDailyPoint] = Field(default_factory=list)


class ChatBiCategoryItem(NorthStarPayload):
    category: str
    category_display_name: str
    answer_total: int = Field(ge=0)


class ChatBiCategoriesResponse(BaseModel):
    start_date: date
    end_date: date
    items: list[ChatBiCategoryItem] = Field(default_factory=list)


class ChatBiRollupResponse(BaseModel):
    start_date: date
    end_date: date
    rows_written: int = Field(ge=0)
