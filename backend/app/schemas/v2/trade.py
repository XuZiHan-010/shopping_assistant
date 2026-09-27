"""购物车、订单与履约事件契约；顾客侧只见库存档位，金额全部为整数分。"""

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

from app.schemas.v2.common import CursorPage, IdempotentWriteRequest, MoneyCents
from app.schemas.v2.shop_session import ImageUrl, StockBand

PublicId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
MAX_LINE_QUANTITY = 99
MAX_LINES = 50
Quantity = Annotated[int, Field(strict=True, ge=1, le=MAX_LINE_QUANTITY)]


class TradeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    CLOSED = "CLOSED"


class FulfillmentStatus(StrEnum):
    NOT_SHIPPED = "NOT_SHIPPED"
    SHIPPED = "SHIPPED"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"


class OrderAfterSaleProjection(StrEnum):
    """订单级聚合投影，不同于售后单自身的状态机。"""

    NONE = "NONE"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CloseReason(StrEnum):
    USER_CANCELLED = "USER_CANCELLED"
    PAYMENT_TIMEOUT = "PAYMENT_TIMEOUT"


class CartItem(TradeModel):
    product_id: PublicId
    name: str = Field(min_length=1, max_length=200)
    image_url: ImageUrl | None
    quantity: Quantity
    unit_price_cents: MoneyCents
    line_total_cents: MoneyCents
    stock_band: StockBand

    @model_validator(mode="after")
    def line_total_matches(self) -> Self:
        if self.line_total_cents != self.unit_price_cents * self.quantity:
            raise ValueError("购物车行小计必须等于单价乘数量")
        return self


class CartResponse(TradeModel):
    items: list[CartItem] = Field(max_length=MAX_LINES)
    subtotal_cents: MoneyCents

    @model_validator(mode="after")
    def consistent_cart(self) -> Self:
        if len({item.product_id for item in self.items}) != len(self.items):
            raise ValueError("购物车商品不得重复")
        if self.subtotal_cents != sum(item.line_total_cents for item in self.items):
            raise ValueError("购物车合计必须等于各行之和")
        return self


class CartItemSetRequest(TradeModel):
    """设置绝对数量而非增量，天然幂等，因此不携带 client_request_id。"""

    quantity: int = Field(strict=True, ge=0, le=MAX_LINE_QUANTITY)


class OrderCreateRequest(IdempotentWriteRequest):
    coupon_id: PublicId | None = None


class OrderPayRequest(IdempotentWriteRequest):
    pass


class OrderCancelRequest(IdempotentWriteRequest):
    pass


class OrderItemPriceSnapshot(TradeModel):
    order_item_id: PublicId
    product_id: PublicId
    name: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    unit_price_cents: MoneyCents
    discount_cents: MoneyCents
    line_total_cents: MoneyCents

    @model_validator(mode="after")
    def consistent_snapshot(self) -> Self:
        gross = self.unit_price_cents * self.quantity
        if self.discount_cents > gross:
            raise ValueError("行优惠不得超过行原价")
        if self.line_total_cents != gross - self.discount_cents:
            raise ValueError("行实付必须等于原价减优惠")
        return self


class OrderSummary(TradeModel):
    id: PublicId
    payment_status: PaymentStatus
    fulfillment_status: FulfillmentStatus
    after_sale_status: OrderAfterSaleProjection
    total_cents: MoneyCents
    item_count: int = Field(strict=True, ge=1)
    created_at: UtcDatetime
    pay_by: UtcDatetime

    @model_validator(mode="after")
    def fulfillment_requires_payment(self) -> Self:
        if (
            self.fulfillment_status != FulfillmentStatus.NOT_SHIPPED
            and self.payment_status != PaymentStatus.PAID
        ):
            raise ValueError("未支付订单不得进入履约")
        if self.pay_by < self.created_at:
            raise ValueError("支付截止不得早于创建时间")
        return self


class OrderDetailResponse(OrderSummary):
    """三维投影加价格快照；履约事件不内嵌，只由分页端点提供。"""

    items: list[OrderItemPriceSnapshot] = Field(min_length=1, max_length=MAX_LINES)
    subtotal_cents: MoneyCents
    discount_cents: MoneyCents
    coupon_id: PublicId | None
    paid_at: UtcDatetime | None
    closed_at: UtcDatetime | None
    close_reason: CloseReason | None
    is_demo: Literal[True]

    @model_validator(mode="after")
    def consistent_order(self) -> Self:
        if len({item.order_item_id for item in self.items}) != len(self.items):
            raise ValueError("订单行不得重复")
        subtotal = sum(item.unit_price_cents * item.quantity for item in self.items)
        discount = sum(item.discount_cents for item in self.items)
        if self.subtotal_cents != subtotal or self.discount_cents != discount:
            raise ValueError("订单原价与优惠必须等于各行之和")
        if self.total_cents != sum(item.line_total_cents for item in self.items) or (
            self.total_cents != self.subtotal_cents - self.discount_cents
        ):
            raise ValueError("订单应付必须等于各行实付之和")
        if self.item_count != sum(item.quantity for item in self.items):
            raise ValueError("件数必须等于各行数量之和")
        paid = self.payment_status == PaymentStatus.PAID
        closed = self.payment_status == PaymentStatus.CLOSED
        if paid != (self.paid_at is not None):
            raise ValueError("支付时间仅在已支付订单出现")
        if closed != (self.closed_at is not None) or closed != (self.close_reason is not None):
            raise ValueError("关闭时间与原因仅在已关闭订单成对出现")
        return self


class FulfillmentEventType(StrEnum):
    ORDER_PLACED = "ORDER_PLACED"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    SHIPPED = "SHIPPED"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    ORDER_CLOSED = "ORDER_CLOSED"


class FulfillmentEvent(TradeModel):
    id: PublicId
    event_type: FulfillmentEventType
    occurred_at: UtcDatetime
    source_timezone: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_+\-/]*$"
    )


class FulfillmentEventPage(CursorPage[FulfillmentEvent]):
    pass


class IllegalTransitionDetail(TradeModel):
    """`ILLEGAL_STATE_TRANSITION.details` 的唯一元素，不含锁或版本等内部信息。"""

    payment_status: PaymentStatus


class UnavailableItemDetail(TradeModel):
    product_id: PublicId
    reason: Literal["OUT_OF_STOCK", "INSUFFICIENT_STOCK", "DELISTED"]
    stock_band: StockBand
