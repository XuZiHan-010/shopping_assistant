"""LLM 允许输出的结构化意图；不含 SQL、表名或任意查询文本。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.schemas.chat import AnswerMode, QuestionCategory


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date


class CrossBusinessPlanType(StrEnum):
    """后端唯一允许执行的跨业务关联类型。"""

    ORDER_TO_REFUND = "ORDER_TO_REFUND"
    ORDER_TO_GOODS = "ORDER_TO_GOODS"
    ORDER_REFUND_GOODS = "ORDER_REFUND_GOODS"


class CrossBusinessPlan(BaseModel):
    """模型只可选择固定关联，不可提供表、列、SQL 或 join 条件。"""

    model_config = ConfigDict(extra="forbid")

    plan_type: CrossBusinessPlanType
    sub_order_no: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )


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
    cross_business_plan: CrossBusinessPlan | None = None
    # 只在本模型的前置校验器中写入。它不会参与 model_dump，因此不会进入查询
    # 或给 LLM 的 JSON 约束；白名单校验器会把它转换为固定的用户可见说明。
    cross_business_plan_rejected: SkipJsonSchema[bool] = Field(
        default=False, exclude=True, repr=False
    )
    # 兼容 Task 10 前写入的 fixture：缺失时维持原有的「明细带分析」行为；
    # 正式提示词要求模型每次明确输出，且这个字段绝不参与 SQL 或字段选择。
    analysis_requested: bool = True

    @model_validator(mode="before")
    @classmethod
    def _clear_invalid_cross_business_plan(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        # 不信任模型自行提交的内部状态；只有本校验器可设置拒绝标记。
        data.pop("cross_business_plan_rejected", None)
        raw_plan = data.get("cross_business_plan")
        if raw_plan is None:
            return data
        try:
            data["cross_business_plan"] = CrossBusinessPlan.model_validate(raw_plan)
        except ValidationError:
            data["cross_business_plan"] = None
            data["cross_business_plan_rejected"] = True
        return data
