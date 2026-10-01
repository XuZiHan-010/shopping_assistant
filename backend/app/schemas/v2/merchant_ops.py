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

from app.schemas.v2.common import (
    MAX_MONEY_CENTS,
    DegradationMixin,
    IdempotentWriteRequest,
    MoneyCents,
)
from app.schemas.v2.shop_session import CouponSummary

PublicId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(UTC))]
MAX_BRIEF_ITEMS = 6
MAX_SIGNAL_REFS = 50
MAX_ATTRIBUTION_SEGMENTS = 5
MAX_SECONDARY_METRICS = 3
MAX_RATIO_BP = 1_000_000

SignedMoneyCents = Annotated[int, Field(strict=True, ge=-MAX_MONEY_CENTS, le=MAX_MONEY_CENTS)]
"""净成交额与贡献值可为负（退款大于成交），不能用非负的 MoneyCents 表示（§8.12.4）。"""

RatioBp = Annotated[int, Field(strict=True, ge=-MAX_RATIO_BP, le=MAX_RATIO_BP)]


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


# ---------------------------------------------------------------------------
# 首页经营主指标与订单只读面（§8.12.4，2026-09-28 补入）
# ---------------------------------------------------------------------------


class OverviewPeriod(OpsModel):
    start: date
    end: date
    label: str = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def consistent_period(self) -> Self:
        if self.start > self.end:
            raise ValueError("周期起始不得晚于结束")
        if (self.end - self.start).days > 6:
            raise ValueError("周期跨度不得超过 7 天")
        return self


class OverviewMetricPoint(OpsModel):
    date: date
    value_cents: SignedMoneyCents


class OverviewHeadline(OpsModel):
    metric_code: Literal["net_gmv"] = "net_gmv"
    current_cents: SignedMoneyCents
    baseline_cents: SignedMoneyCents | None
    change_ratio_bp: RatioBp | None
    current_series: list[OverviewMetricPoint]
    baseline_series: list[OverviewMetricPoint]

    @model_validator(mode="after")
    def consistent_headline(self) -> Self:
        if self.current_cents != sum(point.value_cents for point in self.current_series):
            raise ValueError("本期主指标必须等于本期序列之和")
        if self.baseline_cents is not None:
            if self.baseline_cents != sum(point.value_cents for point in self.baseline_series):
                raise ValueError("基期主指标必须等于基期序列之和")
            if len(self.baseline_series) != len(self.current_series):
                raise ValueError("基期序列必须与本期序列等长")
        elif self.baseline_series:
            raise ValueError("基期无可比数据时基期序列必须为空")
        if self.change_ratio_bp is not None and (
            self.baseline_cents is None or self.baseline_cents <= 0
        ):
            raise ValueError("基期为空或非正时相对变化必须为 null")
        return self


class OverviewAttributionMode(StrEnum):
    SHARE = "SHARE"
    ABSOLUTE_CONTRIBUTION = "ABSOLUTE_CONTRIBUTION"
    STOPPED = "STOPPED"


class OverviewAttributionSegment(OpsModel):
    name: str = Field(min_length=1, max_length=64)
    current_cents: SignedMoneyCents
    baseline_cents: SignedMoneyCents
    contribution_cents: SignedMoneyCents
    share_bp: RatioBp | None

    @model_validator(mode="after")
    def consistent_segment(self) -> Self:
        if self.contribution_cents != self.current_cents - self.baseline_cents:
            raise ValueError("类目贡献必须等于本期减基期")
        return self


class OverviewAttribution(OpsModel):
    dimension: Literal["category"] = "category"
    mode: OverviewAttributionMode
    segments: list[OverviewAttributionSegment] = Field(max_length=MAX_ATTRIBUTION_SEGMENTS)
    remaining_count: int = Field(strict=True, ge=0)
    remaining_contribution_cents: SignedMoneyCents
    stopped_reason: str | None = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def consistent_attribution(self) -> Self:
        if self.mode == OverviewAttributionMode.STOPPED:
            if self.segments:
                raise ValueError("STOPPED 时归因分项必须为空")
            if self.stopped_reason is None:
                raise ValueError("STOPPED 时必须给出安全可理解的原因")
        elif self.stopped_reason is not None:
            raise ValueError("非 STOPPED 时不得给出停止原因")
        for item in self.segments:
            has_share = item.share_bp is not None
            if (self.mode == OverviewAttributionMode.SHARE) != has_share:
                raise ValueError("share_bp 只能在 SHARE 模式下非空")
        return self


# 机器码须与 `app/analytics/contract.py` 的受控指标注册表一致；注册表变动时需同步本处字面值。
OverviewSecondaryMetricCode = Literal["order_count", "refund_amount", "return_rate"]


class OverviewSecondaryUnit(StrEnum):
    COUNT = "COUNT"
    CENTS = "CENTS"
    RATIO_BP = "RATIO_BP"


_SECONDARY_UNIT_BY_CODE: dict[str, OverviewSecondaryUnit] = {
    "order_count": OverviewSecondaryUnit.COUNT,
    "refund_amount": OverviewSecondaryUnit.CENTS,
    "return_rate": OverviewSecondaryUnit.RATIO_BP,
}


class OverviewSecondaryMetric(OpsModel):
    metric_code: OverviewSecondaryMetricCode
    unit: OverviewSecondaryUnit
    current_value: int | None = Field(strict=True, ge=0)
    baseline_value: int | None = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def unit_matches_code(self) -> Self:
        if self.unit != _SECONDARY_UNIT_BY_CODE[self.metric_code]:
            raise ValueError("辅助指标单位必须与固定映射一致")
        return self


class MerchantMetricsOverviewSource(StrEnum):
    REALTIME = "REALTIME"
    DAILY_ROLLUP = "DAILY_ROLLUP"
    MIXED = "MIXED"


_SECONDARY_ORDER: tuple[OverviewSecondaryMetricCode, ...] = (
    "order_count",
    "refund_amount",
    "return_rate",
)


class MerchantMetricsOverviewResponse(DegradationMixin):
    business_timezone: str = Field(min_length=1, max_length=64)
    data_as_of: UtcDatetime
    source: MerchantMetricsOverviewSource
    definition_version: str = Field(min_length=1, max_length=64)
    current_period: OverviewPeriod
    baseline_period: OverviewPeriod
    headline: OverviewHeadline
    attribution: OverviewAttribution
    secondary: list[OverviewSecondaryMetric] = Field(
        min_length=MAX_SECONDARY_METRICS, max_length=MAX_SECONDARY_METRICS
    )

    @model_validator(mode="after")
    def consistent_secondary(self) -> Self:
        codes = tuple(item.metric_code for item in self.secondary)
        if codes != _SECONDARY_ORDER:
            raise ValueError(
                "辅助指标必须恰好 3 项且顺序固定为 order_count、refund_amount、return_rate"
            )
        return self

    @model_validator(mode="after")
    def consistent_attribution_identity(self) -> Self:
        """归因贡献恒等式（§8.12.4）：仅在 mode ≠ STOPPED 且基期有可比数据时可计算左右两侧，
        因此只在这一无歧义切片上强制校验；STOPPED 或基期为空的语义留给 Task 2 服务层。"""
        if (
            self.attribution.mode != OverviewAttributionMode.STOPPED
            and self.headline.baseline_cents is not None
        ):
            segment_total = sum(
                segment.contribution_cents for segment in self.attribution.segments
            )
            left = segment_total + self.attribution.remaining_contribution_cents
            right = self.headline.current_cents - self.headline.baseline_cents
            if left != right:
                raise ValueError(
                    "归因分项贡献与剩余贡献之和必须等于主指标本期与基期之差"
                )
        return self
