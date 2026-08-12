"""LLM 允许输出的结构化意图；不含 SQL、表名或任意查询文本。"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.chat import AnswerMode, QuestionCategory


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date


class QueryIntent(BaseModel):
    """模型输出的唯一查询计划落点，额外字段一律拒绝。"""

    model_config = ConfigDict(extra="forbid")

    answer_mode: AnswerMode
    category: QuestionCategory
    metric: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    filters: dict[str, str] = Field(default_factory=dict)
    date_range: DateRange | None = None
    sort: str | None = None
    limit: int | None = None
    followup_reference: bool = False
    needs_attachment: bool = False
    # 兼容 Task 10 前写入的 fixture：缺失时维持原有的「明细带分析」行为；
    # 正式提示词要求模型每次明确输出，且这个字段绝不参与 SQL 或字段选择。
    analysis_requested: bool = True
