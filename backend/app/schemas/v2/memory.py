"""双端记忆、商家回答反馈与 MCP 只读工具白名单。

MCP 请求/响应直接使用官方 SDK 的协议类型，这里只冻结 SDK 之外的边界（协议版本与工具白名单）。
"""

from datetime import UTC
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.feedback import FeedbackReaction
from app.schemas.v2.common import CursorPage, IdempotentWriteRequest
from app.schemas.v2.shop_session import ShopSlug

PublicId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
MCP_PROTOCOL_VERSION = "2026-07-28"
MAX_SUMMARIES = 20


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryLayer(StrEnum):
    FACT = "FACT"
    SUMMARY = "SUMMARY"


class CustomerMemoryItem(MemoryModel):
    """按顾客 + 店铺隔离；不含服务端解析的顾客与商家内部标识。"""

    id: PublicId
    shop_slug: ShopSlug
    category: str = Field(min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)
    last_confirmed_at: UtcDatetime
    expires_at: UtcDatetime

    @model_validator(mode="after")
    def expires_after_confirmation(self) -> Self:
        if self.expires_at <= self.last_confirmed_at:
            raise ValueError("过期时间必须晚于最后确认时间")
        return self


class CustomerMemoriesResponse(MemoryModel):
    memory_enabled: bool
    memories: CursorPage[CustomerMemoryItem]


class MemoryPreferenceRequest(MemoryModel):
    """关闭记忆须显式确认：条件必填，不是无条件必填。设置绝对状态，天然幂等。"""

    enabled: bool
    purge_confirmation: Literal["yes"] | None = None

    @model_validator(mode="after")
    def confirmation_matches_intent(self) -> Self:
        if not self.enabled and self.purge_confirmation is None:
            raise ValueError("关闭记忆并清空已有记忆前必须显式确认")
        if self.enabled and self.purge_confirmation is not None:
            raise ValueError("开启记忆不接受清空确认")
        return self


class MemoryPreferenceResponse(MemoryModel):
    memory_enabled: bool
    purged_count: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def purge_only_when_disabled(self) -> Self:
        if self.memory_enabled and self.purged_count:
            raise ValueError("开启状态下不会清空记忆")
        return self


class MemorySourceRef(MemoryModel):
    conversation_id: PublicId
    message_id: PublicId


class MerchantMemoryItem(MemoryModel):
    id: PublicId
    layer: MemoryLayer
    category: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=2000)
    source_ref: MemorySourceRef | None
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def source_matches_layer(self) -> Self:
        if self.layer == MemoryLayer.FACT and self.source_ref is None:
            raise ValueError("事实层记忆必须带来源引用")
        if self.layer == MemoryLayer.SUMMARY and self.source_ref is not None:
            raise ValueError("总结层是可重建文档，不携带单条来源")
        return self


class MerchantMemoriesResponse(MemoryModel):
    facts: CursorPage[MerchantMemoryItem]
    summaries: list[MerchantMemoryItem] = Field(max_length=MAX_SUMMARIES)

    @model_validator(mode="after")
    def layers_are_separated(self) -> Self:
        if any(item.layer != MemoryLayer.FACT for item in self.facts.items):
            raise ValueError("事实分页只能包含事实层记忆")
        if any(item.layer != MemoryLayer.SUMMARY for item in self.summaries):
            raise ValueError("总结列表只能包含总结层记忆")
        if len({item.category for item in self.summaries}) != len(self.summaries):
            raise ValueError("每个类别只有一份总结文档")
        return self


class MerchantMemoryDeleteResponse(MemoryModel):
    deleted_id: PublicId
    summary_rebuild_scheduled: bool


class FeedbackKind(StrEnum):
    ADOPTION = "ADOPTION"
    REACTION = "REACTION"


class V2FeedbackRequest(IdempotentWriteRequest):
    """采纳与赞踩语义不同，每次只改其中一种，互不覆盖。"""

    kind: FeedbackKind
    adopted: bool | None = None
    reaction: FeedbackReaction | None = None
    reason: Reason | None = None

    @model_validator(mode="after")
    def fields_match_kind(self) -> Self:
        if self.kind == FeedbackKind.ADOPTION:
            if self.adopted is None:
                raise ValueError("采纳反馈必须给出是否采纳")
            if self.reaction is not None or self.reason is not None:
                raise ValueError("采纳反馈不携带赞踩或原因")
        else:
            if self.adopted is not None:
                raise ValueError("赞踩反馈不携带采纳状态")
            if self.reason is not None and self.reaction is None:
                raise ValueError("撤销赞踩时不得携带原因")
        return self


class V2FeedbackResponse(MemoryModel):
    answer_id: PublicId
    adopted: bool
    reaction: FeedbackReaction | None
    reason: Reason | None
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def reason_requires_reaction(self) -> Self:
        if self.reason is not None and self.reaction is None:
            raise ValueError("原因必须附着在赞踩上")
        return self


class McpReadOnlyTool(StrEnum):
    """`POST /merchant/mcp` 的工具白名单：只有纯读取工具。

    不含 `draft_*` 写工具，也不含会写简报版本或导出记录的 `regenerate_brief`、`create_export`，
    以及不外发给第三方客户端的 `list_signals`。名称以 N3 实际注册表为准。
    """

    QUERY_METRICS = "query_metrics"
    ATTRIBUTE_CHANGE = "attribute_change"
    GET_INVENTORY_ALERTS = "get_inventory_alerts"
    GET_PRODUCT_CONTENT = "get_product_content"
    LIST_COUPONS = "list_coupons"
    GET_METRIC_DEFINITION = "get_metric_definition"
    SEARCH_RULES = "search_rules"
