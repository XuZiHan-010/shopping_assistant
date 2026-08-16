"""LLM 允许输出的结构化意图；不含 SQL、表名或任意查询文本。"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from app.schemas.chat import AnswerMode, QuestionCategory


def _recover_optional_plan[PlanT: BaseModel](
    data: dict[str, object], plan_key: str, rejected_key: str, model_cls: type[PlanT]
) -> None:
    """就地把 `data[plan_key]` 校验成 `model_cls`；校验失败则置空并打拒绝标记。

    供 `QueryIntent._recover_nested_plans` 对每个可选的受控计划字段调用——
    不信任模型给出的嵌套计划形状，失败必须降级而不是让 `ValidationError` 冒泡。
    """

    raw = data.get(plan_key)
    if raw is None:
        return
    try:
        data[plan_key] = model_cls.model_validate(raw)
    except ValidationError:
        data[plan_key] = None
        data[rejected_key] = True


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


class GeneratedMetricPlan(BaseModel):
    """受控临时分组指标的展示信息和唯一允许的分组/筛选列。"""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    group_by: Literal["spu_id", "address_city_name"] | None = None
    filter_column: Literal["spu_id", "address_city_name"] | None = None
    filter_value: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None

    @model_validator(mode="after")
    def _check_shape(self) -> GeneratedMetricPlan:
        if (self.filter_column is None) != (self.filter_value is None):
            raise ValueError("filter_column 与 filter_value 必须同时存在")
        if self.group_by is None and self.filter_column != "address_city_name":
            raise ValueError("无分组时仅允许按城市筛选")
        return self


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
    generated_metric_plan: GeneratedMetricPlan | None = None
    generated_metric_plan_rejected: SkipJsonSchema[bool] = Field(
        default=False, exclude=True, repr=False
    )
    # 兼容 Task 10 前写入的 fixture：缺失时维持原有的「明细带分析」行为；
    # 正式提示词要求模型每次明确输出，且这个字段绝不参与 SQL 或字段选择。
    analysis_requested: bool = True

    @model_validator(mode="before")
    @classmethod
    def _recover_nested_plans(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        # 不信任模型自行提交的内部状态；只有本校验器可设置拒绝标记。
        data.pop("cross_business_plan_rejected", None)
        data.pop("generated_metric_plan_rejected", None)
        _recover_optional_plan(
            data, "cross_business_plan", "cross_business_plan_rejected", CrossBusinessPlan
        )
        _recover_optional_plan(
            data, "generated_metric_plan", "generated_metric_plan_rejected", GeneratedMetricPlan
        )
        return data
