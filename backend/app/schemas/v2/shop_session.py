"""顾客会话与公开店铺目录契约；身份与精确库存不进入公开模型。"""

from collections.abc import Collection
from datetime import UTC
from enum import StrEnum
from ipaddress import ip_address
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.core.session import SessionRole
from app.schemas.chat import AnalysisSource
from app.schemas.v2.common import (
    CursorPage,
    IdempotentWriteRequest,
    MoneyCents,
    V2ChatResponseBase,
)
from app.schemas.v2.common import ShopSlug as ShopSlug

PublicId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
SessionToken = Annotated[
    str, StringConstraints(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


class ShopModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShopSessionCreateRequest(ShopModel):
    shop_slug: ShopSlug


class ShopSessionCreateResponse(ShopModel):
    session_id: SessionToken
    role: Literal[SessionRole.CUSTOMER]
    expires_at: UtcDatetime


class DemoCustomerBindRequest(ShopModel):
    pass


class DemoCustomerBindResponse(ShopModel):
    role: Literal[SessionRole.CUSTOMER]
    is_bound: Literal[True]
    expires_at: UtcDatetime
    # 合并时发生数量截顶、剔除不可售商品或超行数截断即为 true；幂等重绑不再合并，恒为 false。
    cart_adjusted: bool = Field(strict=True)


class StoreProfileResponse(ShopModel):
    shop_slug: ShopSlug
    display_name: str = Field(min_length=1, max_length=120)
    rules_summary: str = Field(max_length=10000)


class StockBand(StrEnum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


def validate_image_url(value: str) -> str:
    """两类顾客图片共用的结构校验；外部主机白名单另由服务层判定。"""
    if not 1 <= len(value) <= 2048:
        raise ValueError("图片地址长度不合法")
    if any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        raise ValueError("图片地址包含非法字符")
    parsed = urlsplit(value)
    if value.startswith("/demo/products/"):
        suffix = parsed.path.removeprefix("/demo/products/")
        if (
            not suffix
            or parsed.query
            or parsed.fragment
            or "%" in value
            or any(part in {"", ".", ".."} for part in suffix.split("/"))
        ):
            raise ValueError("图片必须使用受控静态路径")
        return value
    host = parsed.hostname or ""
    try:
        ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("图片主机不得为 IP 地址")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.fragment
    ):
        raise ValueError("图片地址不符合安全要求")
    return value


ImageUrl = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2048),
    AfterValidator(validate_image_url),
]


class ProductSummary(ShopModel):
    id: PublicId
    name: str = Field(min_length=1, max_length=200)
    short_description: str = Field(max_length=500)
    price_cents: MoneyCents
    stock_band: StockBand
    image_url: ImageUrl | None
    source_locale: Literal["zh-CN", "en-US", "mixed", "und"]
    content_version: int = Field(strict=True, ge=1)
    requested_locale: Literal["zh-CN", "en-US"]
    name_translation_status: Literal["SOURCE", "MACHINE", "FALLBACK"]
    short_description_translation_status: Literal["SOURCE", "MACHINE", "FALLBACK"]
    #: 类目源值，不翻译；前端按固定词表显示（契约 §8.8.1）。
    category: str = Field(min_length=1, max_length=64)


def is_trusted_image_host(url: str, allowed_hosts: Collection[str]) -> bool:
    """仅在地址结构安全且主机受信时放行；本地静态路径无需主机白名单。"""
    try:
        validate_image_url(url)
    except ValueError:
        return False
    if url.startswith("/demo/products/"):
        return True
    host = urlsplit(url).hostname
    return host is not None and host in allowed_hosts


class ProductAttribute(ShopModel):
    name: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)
    source: Literal["MERCHANT", "DEMO"]
    updated_at: UtcDatetime
    name_translation_status: Literal["SOURCE", "MACHINE", "FALLBACK"]
    value_translation_status: Literal["SOURCE", "MACHINE", "FALLBACK"]


class ProductDetailResponse(ProductSummary):
    description: str = Field(max_length=20000)
    attributes: list[ProductAttribute] = Field(max_length=100)
    description_translation_status: Literal["SOURCE", "MACHINE", "FALLBACK"]
    missing_attributes: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_attributes(self) -> Self:
        if len({item.name for item in self.attributes}) != len(self.attributes):
            raise ValueError("属性名称不得重复")
        if len(set(self.missing_attributes)) != len(self.missing_attributes):
            raise ValueError("缺失属性名称不得重复")
        return self


class CouponSummary(ShopModel):
    id: PublicId
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["AMOUNT_OFF", "PERCENT_OFF"]
    min_spend_cents: MoneyCents
    amount_off_cents: MoneyCents | None
    discount_bps: int | None = Field(strict=True, ge=1, le=9999)
    product_ids: list[PublicId] = Field(max_length=100)
    starts_at: UtcDatetime
    ends_at: UtcDatetime

    @model_validator(mode="after")
    def consistent_coupon(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("优惠券结束时间必须晚于开始时间")
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("优惠券商品不得重复")
        if self.kind == "AMOUNT_OFF":
            if not self.amount_off_cents or self.discount_bps is not None:
                raise ValueError("满减券必须提供正金额且不携带折扣比例")
        elif self.amount_off_cents is not None or self.discount_bps is None:
            raise ValueError("折扣券必须提供比例且不携带满减金额")
        return self


class ShopChatRequest(IdempotentWriteRequest):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    conversation_id: PublicId | None = None


class ShopAnswerMode(StrEnum):
    SHOP_GUIDE = "SHOP_GUIDE"
    ORDER = "ORDER"
    AFTER_SALE = "AFTER_SALE"
    CHAT = "CHAT"
    INVALID = "INVALID"


class ShopChatResponse(V2ChatResponseBase):
    answer_mode: ShopAnswerMode

    @model_validator(mode="after")
    def conversational_source(self) -> Self:
        if self.answer_mode in {ShopAnswerMode.CHAT, ShopAnswerMode.INVALID} and (
            len(self.analysis_sources) != 1
            or self.analysis_sources[0].source != AnalysisSource.NONE
        ):
            raise ValueError("普通对话与拒答只使用 NONE 来源")
        return self


class ShopConversationSummary(ShopModel):
    id: PublicId
    title: str = Field(min_length=1, max_length=200)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ShopConversationMessage(ShopModel):
    id: PublicId
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)
    created_at: UtcDatetime
    answer: ShopChatResponse | None

    @model_validator(mode="after")
    def answer_matches_message(self) -> Self:
        if self.role == "user" and self.answer is not None:
            raise ValueError("顾客消息不得携带最终回答")
        if self.role == "assistant" and (self.answer is None or self.content != self.answer.answer):
            raise ValueError("助手消息必须与完整回答一致")
        return self


class ShopConversationDetailResponse(ShopModel):
    conversation: ShopConversationSummary
    messages: CursorPage[ShopConversationMessage]
