"""Chat API 的稳定 Pydantic 契约。"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.feedback import FeedbackReaction


class AnswerMode(StrEnum):
    """回答模式。ATTACHMENT 为 P1 预留值，B2 不产生该模式。"""

    METRIC = "METRIC"
    DETAIL = "DETAIL"
    RULE = "RULE"
    IDENTITY = "IDENTITY"
    CHAT = "CHAT"
    INVALID = "INVALID"
    ATTACHMENT = "ATTACHMENT"


class QualityStatus(StrEnum):
    PASSED = "PASSED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"


class AnalysisSource(StrEnum):
    DATABASE = "DATABASE"
    KNOWLEDGE = "KNOWLEDGE"
    ATTACHMENT = "ATTACHMENT"
    MEMORY = "MEMORY"
    FALLBACK = "FALLBACK"
    NONE = "NONE"


class MetricStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    UNVERIFIED = "UNVERIFIED"


class MetricDefinitionSource(StrEnum):
    METRIC_CATALOG = "METRIC_CATALOG"
    FIELD_COMMENT = "FIELD_COMMENT"
    AI_GENERATED = "AI_GENERATED"

    @classmethod
    def _missing_(cls, value: object) -> MetricDefinitionSource | None:
        # 兼容 0009 迁移前保存的来源文本；新响应只输出枚举值。
        legacy = {
            "Borough 指标目录": cls.METRIC_CATALOG,
            "大模型生成": cls.AI_GENERATED,
        }
        return legacy.get(value) if isinstance(value, str) else None


class ChartType(StrEnum):
    """后端允许的图表类型。

    约束在契约侧声明后由 OpenAPI 自动传给前端，Adapter 无须自行窄化自由字符串。
    """

    LINE = "LINE"
    BAR = "BAR"
    PIE = "PIE"


class QuestionCategory(StrEnum):
    """商家问题的业务分类。

    逐字对应参考实现 `model/QuestionCategory.java`——业务域按 1:1 复刻，
    B3 的意图分类会直接路由到这些值，少一个就会出现无法归类的问题。
    枚举值是对外契约码，只能是英文；中文名见 `CATEGORY_DISPLAY_NAMES`。
    """

    PLATFORM_RULE = "PLATFORM_RULE"
    TRADE = "TRADE"
    REFUND = "REFUND"
    CS_TICKET = "CS_TICKET"
    COMPENSATION = "COMPENSATION"
    COUPON = "COUPON"
    GOODS = "GOODS"
    MERCHANT_OTHER = "MERCHANT_OTHER"
    IDENTITY = "IDENTITY"
    SCM = "SCM"
    UNKNOWN = "UNKNOWN"


CATEGORY_DISPLAY_NAMES: dict[QuestionCategory, str] = {
    QuestionCategory.PLATFORM_RULE: "平台商家规则",
    QuestionCategory.TRADE: "电商交易",
    QuestionCategory.REFUND: "电商退货",
    QuestionCategory.CS_TICKET: "电商客服工单",
    QuestionCategory.COMPENSATION: "电商理赔/赔付",
    QuestionCategory.COUPON: "电商优惠券",
    QuestionCategory.GOODS: "商品管理",
    QuestionCategory.MERCHANT_OTHER: "商家其他信息",
    QuestionCategory.IDENTITY: "身份信息",
    QuestionCategory.SCM: "供应链",
    QuestionCategory.UNKNOWN: "未知",
}


class ThinkingStep(BaseModel):
    label: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    node: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class QueryPlanSummary(BaseModel):
    summary: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ExportInfo(BaseModel):
    id: UUID
    url: str
    expires_at: datetime


class Visualization(BaseModel):
    enabled: bool
    type: ChartType | None = None
    allowed_types: list[ChartType] = Field(default_factory=list)
    title: str | None = None
    dimension_key: str | None = None
    metric_key: str | None = None
    unit: str | None = None
    data: list[dict[str, str | int | float | None]] = Field(default_factory=list)


class Recommendation(BaseModel):
    title: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    evidence: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    action: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class ChatRequest(BaseModel):
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000),
    ]
    session_id: UUID | None = None
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=0)
    client_request_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]


class ChatResponse(BaseModel):
    """§8.2 的扁平响应；按模式字段由模型级校验控制。"""

    id: UUID
    session_id: UUID
    answer: Annotated[str, StringConstraints(min_length=1)]
    answer_mode: AnswerMode
    category: QuestionCategory | None
    thinking_steps: list[ThinkingStep] = Field(default_factory=list)
    quality_status: QualityStatus
    quality_attempts: int = Field(ge=0, le=2)
    quality_notes: list[str] = Field(default_factory=list)
    analysis_sources: list[AnalysisSource] = Field(min_length=1)
    degraded: bool
    degraded_reason: str | None
    suggestions: list[str] = Field(default_factory=list)
    suggestion_alternates: list[list[str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    query_plan: QueryPlanSummary | None = None
    metric_code: str | None = None
    metric_display_name: str | None = None
    metric_unit: str | None = None
    metric_definition: str | None = None
    metric_sql_definition: str | None = None
    metric_dimensions: list[str] | None = None
    metric_source_database: str | None = None
    metric_source_table: str | None = None
    metric_report_url: str | None = None
    metric_source: MetricDefinitionSource | None = None
    metric_generated: bool | None = None
    metric_notice: str | None = None
    metric_owner: str | None = None
    metric_status: MetricStatus | None = None
    data_rows: list[dict[str, Any]] | None = None
    total_rows: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    export: ExportInfo | None = None
    visualization: Visualization | None = None
    recommendations: list[Recommendation] | None = None

    @model_validator(mode="after")
    def validate_cross_field_contract(self) -> ChatResponse:
        sources = set(self.analysis_sources)
        if AnalysisSource.NONE in sources and sources != {AnalysisSource.NONE}:
            raise ValueError("analysis_sources 中的 NONE 只能单独出现")
        if self.answer_mode is AnswerMode.INVALID:
            if self.analysis_sources != [AnalysisSource.NONE]:
                raise ValueError("INVALID 必须仅使用 NONE 来源")
            if self.degraded:
                raise ValueError("INVALID 不应标记为降级")
        if (
            self.answer_mode is AnswerMode.CHAT
            and not self.degraded
            and self.analysis_sources != [AnalysisSource.NONE]
        ):
            raise ValueError("未降级的 CHAT 必须仅使用 NONE 来源")
        if (
            self.answer_mode is AnswerMode.CHAT
            and self.degraded
            and self.analysis_sources != [AnalysisSource.FALLBACK]
        ):
            raise ValueError("降级的 CHAT 必须仅使用 FALLBACK 来源")
        if AnalysisSource.FALLBACK in sources and not self.degraded:
            raise ValueError("含 FALLBACK 来源时 degraded 必须为 true")
        if self.degraded and not self.degraded_reason:
            raise ValueError("降级回答必须提供 degraded_reason")
        if not self.degraded and self.degraded_reason is not None:
            raise ValueError("未降级回答的 degraded_reason 必须为 null")

        if self.answer_mode in {AnswerMode.METRIC, AnswerMode.DETAIL, AnswerMode.IDENTITY}:
            self._require("query_plan", self.query_plan)
            self._require("data_rows", self.data_rows)
            self._require("total_rows", self.total_rows)
            self._require("truncated", self.truncated)
        if self.answer_mode is AnswerMode.METRIC:
            for field_name, value in (
                ("metric_code", self.metric_code),
                ("metric_display_name", self.metric_display_name),
                ("metric_unit", self.metric_unit),
                ("metric_definition", self.metric_definition),
                ("metric_sql_definition", self.metric_sql_definition),
                ("metric_dimensions", self.metric_dimensions),
                ("metric_source_database", self.metric_source_database),
                ("metric_source_table", self.metric_source_table),
                ("metric_source", self.metric_source),
                ("metric_generated", self.metric_generated),
                ("metric_owner", self.metric_owner),
                ("metric_status", self.metric_status),
                ("visualization", self.visualization),
            ):
                self._require(field_name, value)
            if self.metric_generated:
                if self.metric_status is not MetricStatus.UNVERIFIED:
                    raise ValueError("metric_generated 为 true 时 metric_status 必须为 UNVERIFIED")
                if self.metric_source is not MetricDefinitionSource.AI_GENERATED:
                    raise ValueError(
                        "metric_generated 为 true 时 metric_source 必须为 AI_GENERATED"
                    )
                self._require("metric_notice", self.metric_notice)
            elif self.metric_notice is not None:
                raise ValueError("metric_generated 为 false 时 metric_notice 必须为 null")
            self._require_recommendations()
        if self.answer_mode is AnswerMode.DETAIL:
            self._require("export", self.export)
            self._require_recommendations()
        if self.answer_mode is AnswerMode.ATTACHMENT:
            self._require_recommendations()
        return self

    @staticmethod
    def _require(field_name: str, value: object | None) -> None:
        if value is None:
            raise ValueError(f"{field_name} 在当前 answer_mode 下必填")

    def _require_recommendations(self) -> None:
        if self.recommendations is None or len(self.recommendations) < 2:
            raise ValueError("recommendations 在当前 answer_mode 下至少需要两条")


class ConversationSummary(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class ConversationMessage(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime
    answer_payload: ConversationAnswerPayload | None = None


class ConversationAnswerPayload(BaseModel):
    """会话详情中的助手回答脱敏载荷，不携带明细行和导出 URL。"""

    answer_id: UUID
    answer_mode: AnswerMode
    thinking_steps: list[ThinkingStep] = Field(default_factory=list)
    quality_status: QualityStatus
    quality_attempts: int = Field(ge=0, le=2)
    quality_notes: list[str] = Field(default_factory=list)
    degraded: bool
    degraded_reason: str | None
    is_adopted: bool
    reaction: FeedbackReaction | None
    columns: list[str] = Field(default_factory=list)
    total_rows: int | None = Field(default=None, ge=0)
    truncated: bool | None = None


class ConversationDetailResponse(BaseModel):
    id: UUID
    title: str | None
    messages: list[ConversationMessage]
    created_at: datetime
    updated_at: datetime
