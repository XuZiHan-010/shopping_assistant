"""双端售后契约；退款金额只由后端计算，商家侧只见脱敏别名。"""

from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
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

from app.schemas.v2.common import IdempotentWriteRequest, MoneyCents
from app.schemas.v2.trade import OrderItemPriceSnapshot

PublicId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
ConfirmationToken = Annotated[
    str, StringConstraints(min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9._~-]+$")
]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
MAX_LINES = 50
MAX_EVENTS = 100
# 创建 1 条、每次补充往返 2 条、最长退货退款结案再需 5 条。
MAX_INFORMATION_REQUESTS = (MAX_EVENTS - 1 - 5) // 2


class AfterSaleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AfterSaleType(StrEnum):
    RETURN_REFUND = "RETURN_REFUND"
    REFUND_ONLY = "REFUND_ONLY"
    TICKET = "TICKET"


class AfterSaleState(StrEnum):
    PENDING_MERCHANT = "PENDING_MERCHANT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AWAITING_RETURN = "AWAITING_RETURN"
    RECEIVED = "RECEIVED"
    REFUNDED = "REFUNDED"
    AWAITING_CUSTOMER_INFO = "AWAITING_CUSTOMER_INFO"
    CLOSED = "CLOSED"


class AfterSaleActor(StrEnum):
    CUSTOMER = "CUSTOMER"
    MERCHANT = "MERCHANT"
    SYSTEM = "SYSTEM"


_ALL_TYPES = frozenset(AfterSaleType)
_REFUND_TYPES = frozenset({AfterSaleType.RETURN_REFUND, AfterSaleType.REFUND_ONLY})
_S = AfterSaleState
_T = AfterSaleType

# 源状态 → 目标状态 → 适用类型，逐跳对应 PRD §7.2 的四条链
# （含客服工单的 APPROVED → CLOSED：工单没有退款与寄回，已同意即已处理）。
ALLOWED_TRANSITIONS: dict[
    tuple[AfterSaleState | None, AfterSaleState], frozenset[AfterSaleType]
] = {
    (None, _S.PENDING_MERCHANT): _ALL_TYPES,
    (_S.PENDING_MERCHANT, _S.APPROVED): _ALL_TYPES,
    (_S.PENDING_MERCHANT, _S.REJECTED): _ALL_TYPES,
    (_S.PENDING_MERCHANT, _S.AWAITING_CUSTOMER_INFO): _ALL_TYPES,
    (_S.AWAITING_CUSTOMER_INFO, _S.PENDING_MERCHANT): _ALL_TYPES,
    (_S.APPROVED, _S.AWAITING_RETURN): frozenset({_T.RETURN_REFUND}),
    (_S.APPROVED, _S.REFUNDED): frozenset({_T.REFUND_ONLY}),
    (_S.AWAITING_RETURN, _S.RECEIVED): frozenset({_T.RETURN_REFUND}),
    (_S.RECEIVED, _S.REFUNDED): frozenset({_T.RETURN_REFUND}),
    (_S.REFUNDED, _S.CLOSED): _REFUND_TYPES,
    (_S.REJECTED, _S.CLOSED): _ALL_TYPES,
    (_S.APPROVED, _S.CLOSED): frozenset({_T.TICKET}),
}


def is_allowed_transition(
    after_sale_type: AfterSaleType,
    from_state: AfterSaleState | None,
    to_state: AfterSaleState,
    *,
    prior_information_requests: int | None = None,
) -> bool:
    if after_sale_type not in ALLOWED_TRANSITIONS.get((from_state, to_state), frozenset()):
        return False
    if (from_state, to_state) == (_S.PENDING_MERCHANT, _S.AWAITING_CUSTOMER_INFO):
        if prior_information_requests is None or prior_information_requests < 0:
            raise ValueError("补充信息次数必须由后端事件账本提供")
        return prior_information_requests < MAX_INFORMATION_REQUESTS
    return True


class AfterSaleCreateRequest(IdempotentWriteRequest):
    """不含金额、可否发起、状态或身份字段：这些一律由后端决定，提交即拒绝。"""

    order_id: PublicId
    after_sale_type: AfterSaleType
    order_item_ids: list[PublicId] = Field(default_factory=list, max_length=MAX_LINES)
    reason: Reason = ""
    include_conversation_summary: bool = False
    confirmation_token: ConfirmationToken | None = None

    @model_validator(mode="after")
    def consistent_request(self) -> Self:
        if len(set(self.order_item_ids)) != len(self.order_item_ids):
            raise ValueError("订单行不得重复")
        if self.after_sale_type == AfterSaleType.TICKET and not self.reason:
            raise ValueError("客服工单必须说明原因")
        return self


class AfterSaleSupplementRequest(IdempotentWriteRequest):
    """顾客在详情页主动提交；金额、状态与身份字段均不接受。"""

    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class AfterSaleSupplement(AfterSaleModel):
    id: PublicId
    note: str = Field(min_length=1, max_length=1000)
    submitted_at: UtcDatetime


class AfterSaleReply(AfterSaleModel):
    id: PublicId
    text: str = Field(min_length=1, max_length=2000)
    sent_at: UtcDatetime


class AfterSaleIneligibleDetail(AfterSaleModel):
    """`GUARDRAIL_REJECTED.details` 元素：说明依据的条款，不许诺特例。"""

    reason: Literal[
        "ORDER_NOT_DELIVERED", "WINDOW_EXPIRED", "ALREADY_IN_PROGRESS", "ALREADY_REFUNDED"
    ]
    rule_reference: str = Field(min_length=1, max_length=200)


class AfterSaleChallengeLine(AfterSaleModel):
    order_item_id: PublicId
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(strict=True, ge=1, le=99)
    line_total_cents: MoneyCents


class AfterSaleChallengeSummary(AfterSaleModel):
    """供人核对的脱敏摘要，不含 token 与身份。"""

    order_id: PublicId
    after_sale_type: AfterSaleType
    lines: list[AfterSaleChallengeLine] = Field(max_length=MAX_LINES)
    estimated_refund_cents: MoneyCents | None
    reason: Reason
    conversation_summary_status: Literal["NOT_SHARED", "INCLUDED", "UNAVAILABLE"]
    conversation_summary: str | None = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def consistent_summary(self) -> Self:
        if (self.after_sale_type == AfterSaleType.TICKET) != (self.estimated_refund_cents is None):
            raise ValueError("仅客服工单没有预计退款金额")
        if (self.conversation_summary_status == "INCLUDED") != (
            self.conversation_summary is not None
        ):
            raise ValueError("对话摘要仅在已包含时出现")
        return self


class AfterSaleConfirmationChallenge(AfterSaleModel):
    confirmation_token: ConfirmationToken
    expires_at: UtcDatetime
    summary: AfterSaleChallengeSummary


class AfterSaleSummary(AfterSaleModel):
    id: PublicId
    order_id: PublicId
    after_sale_type: AfterSaleType
    state: AfterSaleState
    refund_amount_cents: MoneyCents | None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def consistent_summary(self) -> Self:
        if (self.after_sale_type == AfterSaleType.TICKET) != (self.refund_amount_cents is None):
            raise ValueError("仅客服工单没有退款金额")
        if self.updated_at < self.created_at:
            raise ValueError("更新时间不得早于创建时间")
        return self


class AfterSaleLine(AfterSaleModel):
    snapshot: OrderItemPriceSnapshot
    refund_cents: MoneyCents

    @model_validator(mode="after")
    def within_snapshot(self) -> Self:
        if self.refund_cents > self.snapshot.line_total_cents:
            raise ValueError("单行退款不得超过该行快照金额")
        return self


class AfterSaleEvent(AfterSaleModel):
    id: PublicId
    from_state: AfterSaleState | None
    to_state: AfterSaleState
    actor: AfterSaleActor
    occurred_at: UtcDatetime


class AfterSaleDetailBase(AfterSaleSummary):
    reason: Reason
    lines: list[AfterSaleLine] = Field(max_length=MAX_LINES)
    events: list[AfterSaleEvent] = Field(min_length=1, max_length=MAX_EVENTS)
    supplements: list[AfterSaleSupplement] = Field(max_length=MAX_INFORMATION_REQUESTS)
    replies: list[AfterSaleReply] = Field(max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def consistent_detail(self) -> Self:
        ids = [line.snapshot.order_item_id for line in self.lines]
        if len(set(ids)) != len(ids):
            raise ValueError("售后行不得重复")
        if self.after_sale_type == AfterSaleType.TICKET:
            if any(line.refund_cents for line in self.lines):
                raise ValueError("客服工单不产生退款")
        else:
            if not self.lines:
                raise ValueError("退款类售后必须包含订单行")
            if self.refund_amount_cents != sum(line.refund_cents for line in self.lines):
                raise ValueError("退款合计必须等于各行退款之和")
        previous: AfterSaleState | None = None
        previous_order_key: tuple[datetime, str] | None = None
        information_requests = 0
        for event in self.events:
            order_key = (event.occurred_at, event.id)
            if previous_order_key is not None and order_key <= previous_order_key:
                raise ValueError("事件必须按时间与标识升序排列")
            if event.from_state != previous:
                raise ValueError("售后事件必须首尾相接且符合允许迁移表")
            if (event.from_state, event.to_state) == (
                _S.PENDING_MERCHANT,
                _S.AWAITING_CUSTOMER_INFO,
            ):
                if not is_allowed_transition(
                    self.after_sale_type,
                    event.from_state,
                    event.to_state,
                    prior_information_requests=information_requests,
                ):
                    raise ValueError("补充信息次数已达上限")
                information_requests += 1
            elif not is_allowed_transition(self.after_sale_type, event.from_state, event.to_state):
                raise ValueError("售后事件必须首尾相接且符合允许迁移表")
            previous = event.to_state
            previous_order_key = order_key
        if previous != self.state:
            raise ValueError("售后状态必须等于最后一个事件的目标状态")
        supplement_order = [(item.submitted_at, item.id) for item in self.supplements]
        if any(later <= earlier for earlier, later in pairwise(supplement_order)):
            raise ValueError("补充说明必须按时间与标识升序排列")
        return self


class CustomerAfterSaleDetailResponse(AfterSaleDetailBase):
    """顾客侧：无别名、无审计字段。"""

    conversation_summary_shared: bool


class ConversationSnapshot(AfterSaleModel):
    status: Literal["NOT_SHARED", "AVAILABLE", "UNAVAILABLE"]
    text: str | None = Field(min_length=1, max_length=2000)
    unavailable_reason: str | None = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def consistent_snapshot(self) -> Self:
        if (self.status == "AVAILABLE") != (self.text is not None):
            raise ValueError("摘要正文仅在可用时出现")
        if (self.status == "UNAVAILABLE") != (self.unavailable_reason is not None):
            raise ValueError("不可用原因仅在不可用时出现")
        return self


class MerchantAfterSaleSummary(AfterSaleSummary):
    buyer_alias: str = Field(min_length=1, max_length=64)
    first_response_due_at: UtcDatetime


class MerchantAfterSaleDetailResponse(AfterSaleDetailBase):
    """商家侧：顾客只以店铺级脱敏别名出现；查看审计是服务端副作用，不进入响应。"""

    buyer_alias: str = Field(min_length=1, max_length=64)
    first_response_due_at: UtcDatetime
    ticket_id: PublicId
    conversation_summary: ConversationSnapshot
