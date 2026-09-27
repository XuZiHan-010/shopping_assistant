"""商家经营只读面契约：当日简报、库存告警、顾客信号。只消费共用组件。"""

from datetime import UTC, date
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

from app.schemas.v2.common import DegradationMixin, IdempotentWriteRequest, MoneyCents
from app.schemas.v2.shop_session import CouponSummary

PublicId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
MAX_BRIEF_ITEMS = 6
MAX_SIGNAL_REFS = 50


class OpsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DailyBriefItemKind(StrEnum):
    INVENTORY_ALERT = "INVENTORY_ALERT"
    PENDING_DRAFT = "PENDING_DRAFT"
    CUSTOMER_SIGNAL = "CUSTOMER_SIGNAL"
    METRIC_CHANGE = "METRIC_CHANGE"
    ORDER_EXCEPTION = "ORDER_EXCEPTION"


class DailyBriefItem(OpsModel):
    rank: int = Field(strict=True, ge=1)
    kind: DailyBriefItemKind
    title: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=500)
    amount_cents: MoneyCents | None
    next_action_prompt: str | None = Field(min_length=1, max_length=500)


class DailyBriefResponse(DegradationMixin):
    brief_version: int = Field(strict=True, ge=1)
    business_date: date
    business_timezone: str = Field(min_length=1, max_length=64)
    data_as_of: UtcDatetime
    generated_at: UtcDatetime
    trigger: Literal["SCHEDULED", "REGENERATED"]
    items: list[DailyBriefItem] = Field(max_length=MAX_BRIEF_ITEMS)
    collapsed_count: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def consistent_brief(self) -> Self:
        if self.generated_at < self.data_as_of:
            raise ValueError("生成时间不得早于数据截至时间")
        if [item.rank for item in self.items] != list(range(1, len(self.items) + 1)):
            raise ValueError("简报条目排名必须从 1 连续递增")
        return self


class BriefRegenerateRequest(IdempotentWriteRequest):
    pass


class InventoryAlertKind(StrEnum):
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    SLOW_MOVING = "SLOW_MOVING"


class InventoryAlert(OpsModel):
    """商家可见的精确库存三元组；顾客响应只暴露档位。"""

    id: PublicId
    kind: InventoryAlertKind
    product_id: PublicId
    product_name: str = Field(min_length=1, max_length=200)
    stock_on_hand: int = Field(strict=True, ge=0)
    stock_reserved: int = Field(strict=True, ge=0)
    stock_available: int = Field(strict=True, ge=0)
    low_stock_threshold: int = Field(strict=True, ge=0)
    sold_last_30d: int = Field(strict=True, ge=0)
    days_of_supply: int | None = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def consistent_alert(self) -> Self:
        if self.stock_reserved > self.stock_on_hand:
            raise ValueError("占用量不得超过在库量")
        if self.stock_available != self.stock_on_hand - self.stock_reserved:
            raise ValueError("可售量必须等于在库量减占用量")
        if (self.days_of_supply is None) != (self.sold_last_30d == 0):
            raise ValueError("可售天数仅在无近期销量时为空")
        if self.kind == InventoryAlertKind.OUT_OF_STOCK and self.stock_available != 0:
            raise ValueError("售罄告警要求可售量为 0")
        if self.kind == InventoryAlertKind.LOW_STOCK and not (
            0 < self.stock_available <= self.low_stock_threshold
        ):
            raise ValueError("低库存告警要求可售量为正且不超过阈值")
        if self.kind == InventoryAlertKind.SLOW_MOVING and self.stock_available <= 0:
            raise ValueError("滞销告警要求仍有可售量")
        return self


class MerchantProductContent(OpsModel):
    id: PublicId
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)
    content_version: int = Field(strict=True, ge=1)
    missing_required_attributes: list[str]
    missing_content_fields: list[str]
    content_complete: bool
    stock_on_hand: int = Field(strict=True, ge=0)
    stock_reserved: int = Field(strict=True, ge=0)
    stock_available: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def consistent_content(self) -> Self:
        if self.stock_available != self.stock_on_hand - self.stock_reserved:
            raise ValueError("可售库存必须等于在库减占用")
        if self.content_complete != (
            not self.missing_required_attributes and not self.missing_content_fields
        ):
            raise ValueError("内容完整度必须与属性、描述和图片缺口一致")
        return self


class MerchantCoupon(CouponSummary):
    state: str = Field(min_length=1, max_length=32)
    currently_active: bool


class CustomerSignalKind(StrEnum):
    RETURN_REQUESTS = "RETURN_REQUESTS"
    REFUND_REQUESTS = "REFUND_REQUESTS"
    SUPPORT_TICKETS = "SUPPORT_TICKETS"
    CONTENT_GAP = "CONTENT_GAP"


class SignalSourceRef(OpsModel):
    """售后信号指向售后主记录；内容缺口信号指向商品及其内容版本，永不指向顾客对话。"""

    source_type: Literal["AFTER_SALE", "PRODUCT"]
    source_id: PublicId
    content_version: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def version_only_for_product(self) -> Self:
        if (self.source_type == "PRODUCT") != (self.content_version is not None):
            raise ValueError("仅商品来源携带内容版本，且商品来源必须携带")
        return self


class CustomerSignal(OpsModel):
    """派生提醒而非事实源；不含任何顾客标识。"""

    id: PublicId
    kind: CustomerSignalKind
    product_id: PublicId | None
    product_name: str | None = Field(min_length=1, max_length=200)
    signal_date: date
    count: int = Field(strict=True, ge=1)
    derived_from: list[SignalSourceRef] = Field(min_length=1, max_length=MAX_SIGNAL_REFS)
    is_ignored: bool
    ignore_reason: str | None = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def consistent_signal(self) -> Self:
        if (self.product_id is None) != (self.product_name is None):
            raise ValueError("商品标识与名称必须同时出现或同时为空")
        if len({ref.source_id for ref in self.derived_from}) != len(self.derived_from):
            raise ValueError("来源记录不得重复")
        if len(self.derived_from) > self.count:
            raise ValueError("来源记录数不得超过聚合计数")
        if self.kind == CustomerSignalKind.CONTENT_GAP:
            if len(self.derived_from) != 1 or self.derived_from[0].source_type != "PRODUCT":
                raise ValueError("内容缺口信号只有一条商品来源")
            if self.product_id is None or self.derived_from[0].source_id != self.product_id:
                raise ValueError("内容缺口信号的来源必须是信号所指商品")
        elif any(ref.source_type != "AFTER_SALE" for ref in self.derived_from):
            raise ValueError("售后类信号只能来自售后主记录")
        if self.is_ignored != (self.ignore_reason is not None):
            raise ValueError("忽略原因仅在已忽略时出现")
        return self


class SignalIgnoreRequest(IdempotentWriteRequest):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
