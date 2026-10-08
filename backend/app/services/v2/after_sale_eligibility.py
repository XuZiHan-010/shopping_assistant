"""由订单事实计算售后发起资格，不接收模型或客户端的资格判断。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.schemas.v2.after_sales import AfterSaleType

ReasonCode = Literal[
    "ORDER_NOT_DELIVERED", "WINDOW_EXPIRED", "ALREADY_IN_PROGRESS", "ALREADY_REFUNDED"
]


@dataclass(frozen=True)
class OrderFacts:
    lifecycle_origin: str
    payment_status: str
    fulfillment_status: str
    delivered_at: datetime | None
    already_in_progress: bool
    already_refunded: bool


@dataclass(frozen=True)
class Eligibility:
    allowed: bool
    allowed_types: frozenset[AfterSaleType]
    rule_ref: str
    reason_code: ReasonCode | None


def check_eligibility(facts: OrderFacts, *, now: datetime) -> Eligibility:
    """签收后七天内可申请；未签收的已支付订单仅可申请仅退款或工单。"""

    none: frozenset[AfterSaleType] = frozenset()
    if facts.lifecycle_origin != "V2" or facts.payment_status != "PAID":
        return Eligibility(False, none, "平台演示售后规则：仅本版已支付订单可申请", None)
    if facts.already_refunded:
        return Eligibility(
            False, none, "平台演示售后规则：已全额退款不可重复申请", "ALREADY_REFUNDED"
        )
    if facts.already_in_progress:
        return Eligibility(
            False,
            none,
            "平台演示售后规则：同一订单不可重复发起进行中的售后",
            "ALREADY_IN_PROGRESS",
        )
    if facts.fulfillment_status != "DELIVERED":
        return Eligibility(
            True,
            frozenset({AfterSaleType.REFUND_ONLY, AfterSaleType.TICKET}),
            "平台演示售后规则：未签收不受理退货，允许仅退款或工单",
            "ORDER_NOT_DELIVERED",
        )
    if facts.delivered_at is None or now - facts.delivered_at > timedelta(days=7):
        return Eligibility(False, none, "平台演示售后规则：签收后七天内申请", "WINDOW_EXPIRED")
    return Eligibility(True, frozenset(AfterSaleType), "平台演示售后规则：签收后七天内申请", None)
