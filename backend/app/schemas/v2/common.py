"""v2 共用传输组件。金额单位为分，上界对应 Numeric(14, 2) 元。"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.errors import ErrorResponse as ErrorResponse
from app.core.session import SessionRole as SessionRole
from app.schemas.chat import AnalysisSource, QualityStatus, ThinkingStep

MAX_MONEY_CENTS = 99999999999999
MoneyCents = Annotated[int, Field(strict=True, ge=0, le=MAX_MONEY_CENTS)]
SuggestionText = Annotated[str, Field(min_length=1, max_length=200)]
MAX_SUGGESTIONS_PER_GROUP = 3
MAX_SUGGESTION_ALTERNATE_GROUPS = 5
PublicToolSummary = Literal[
    "正在处理",
    "处理完成",
    "暂时不可用",
    "处理失败",
    "Processing",
    "Completed",
    "Unavailable",
    "Failed",
]
V2AnalysisSource = Literal[
    AnalysisSource.DATABASE,
    AnalysisSource.KNOWLEDGE,
    AnalysisSource.MEMORY,
    AnalysisSource.FALLBACK,
    AnalysisSource.NONE,
]


def yuan_to_cents(value: Decimal) -> int:
    """逐行按 ROUND_HALF_UP 舍入，调用方再对整数分求和。"""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("金额必须为有限 Decimal 元")
    if value < 0 or value > Decimal("999999999999.99"):
        raise ValueError("金额超出允许范围")
    return int(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def cents_to_yuan(value: int) -> Decimal:
    """整数分转换为两位小数元，不接受布尔值或隐式数值转换。"""
    if type(value) is not int or not 0 <= value <= MAX_MONEY_CENTS:
        raise ValueError("金额必须为范围内的整数分")
    return (Decimal(value) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class CursorPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    limit: int = Field(default=20, ge=1, le=100)


class CursorPage[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[T]
    next_cursor: str | None = Field(min_length=1, max_length=2048)
    has_more: bool

    @model_validator(mode="after")
    def cursor_matches_has_more(self) -> Self:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("仅在存在下一页时提供下一页游标")
        return self


class IdempotentWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    )


class SseEventName(StrEnum):
    STEP = "step"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TURN_COMPLETE = "turn_complete"
    ERROR = "error"


class ToolDisplayStatus(StrEnum):
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


def _check_degradation(degraded: bool, reason: str | None) -> None:
    if degraded:
        if reason is None or not reason.strip():
            raise ValueError("降级时必须提供非空原因")
    elif reason is not None:
        raise ValueError("未降级时原因必须为 null")


class AnalysisSourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: V2AnalysisSource
    degraded: bool
    degraded_reason: str | None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.source == AnalysisSource.FALLBACK and not self.degraded:
            raise ValueError("规则兜底来源必须标记降级")
        _check_degradation(self.degraded, self.degraded_reason)
        return self


class DegradationMixin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_sources: list[AnalysisSourceEntry] = Field(min_length=1)
    thinking_steps: list[ThinkingStep] = Field(default_factory=list)
    quality_status: QualityStatus
    quality_attempts: int = Field(ge=0, le=3)
    quality_notes: list[str] = Field(default_factory=list)
    degraded: bool
    degraded_reason: str | None

    @model_validator(mode="after")
    def validate_degradation(self) -> Self:
        if len(self.analysis_sources) > 1 and any(
            entry.source == AnalysisSource.NONE for entry in self.analysis_sources
        ):
            raise ValueError("NONE 来源必须独占")
        if (
            any(entry.source == AnalysisSource.FALLBACK for entry in self.analysis_sources)
            and not self.degraded
        ):
            raise ValueError("规则兜底回答必须标记整轮降级")
        _check_degradation(self.degraded, self.degraded_reason)
        return self


_ALLOWED_SUMMARIES: dict[ToolDisplayStatus, frozenset[str]] = {
    ToolDisplayStatus.STARTED: frozenset({"正在处理", "Processing"}),
    ToolDisplayStatus.RUNNING: frozenset({"正在处理", "Processing"}),
    ToolDisplayStatus.SUCCEEDED: frozenset({"处理完成", "Completed"}),
    ToolDisplayStatus.DEGRADED: frozenset({"暂时不可用", "Unavailable"}),
    ToolDisplayStatus.UNAVAILABLE: frozenset({"暂时不可用", "Unavailable"}),
    ToolDisplayStatus.FAILED: frozenset({"处理失败", "Failed"}),
}


def _check_summary_matches_status(status: ToolDisplayStatus, summary: str) -> None:
    if summary not in _ALLOWED_SUMMARIES[status]:
        raise ValueError("工具摘要必须与状态一致")


class ToolCallDisplay(BaseModel):
    """只接受受控的公开状态与短句，不接受模型或工具返回的任意正文。"""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    status: ToolDisplayStatus
    summary: PublicToolSummary

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        _check_summary_matches_status(self.status, self.summary)
        return self


class ToolResultDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    status: ToolDisplayStatus
    duration_ms: int = Field(ge=0)
    row_count: int | None = Field(ge=0)
    summary: PublicToolSummary

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        _check_summary_matches_status(self.status, self.summary)
        return self


class V2ChatResponseBase(DegradationMixin):
    id: str
    conversation_id: str
    answer: str
    tool_calls: list[ToolCallDisplay]
    created_at: datetime
    suggestions: list[SuggestionText] = Field(
        default_factory=list, max_length=MAX_SUGGESTIONS_PER_GROUP
    )
    suggestion_alternates: list[
        Annotated[list[SuggestionText], Field(min_length=1, max_length=MAX_SUGGESTIONS_PER_GROUP)]
    ] = Field(default_factory=list, max_length=MAX_SUGGESTION_ALTERNATE_GROUPS)

    @model_validator(mode="after")
    def validate_suggestions(self) -> Self:
        if self.suggestion_alternates and not self.suggestions:
            raise ValueError("没有当前一组推荐问题时不得提供备选组")
        if any(group == self.suggestions for group in self.suggestion_alternates):
            raise ValueError("备选组不得重复当前一组")
        return self

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value.astimezone(UTC)
