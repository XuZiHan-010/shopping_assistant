"""指标 Seed；metric_code 是唯一内部键，中文名仅用于展示。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class MetricSeedItem:
    metric_code: str
    display_name: str
    unit: str
    business_definition: str
    sql_definition: str
    dimensions: tuple[str, ...]
    source_database: str
    source_table: str
    report_url: str | None = None
    generated: bool = False
    notice: str | None = None
    source: str = "METRIC_CATALOG"
    owner: str = "经营分析组"


METRIC_SEED: Final[tuple[MetricSeedItem, ...]] = (
    MetricSeedItem(
        "gmv",
        "成交 GMV",
        "元",
        "统计周期内已支付订单金额之和。",
        "SUM(orders.paid_amount) WHERE order_status IN ('PAID','SHIPPED','COMPLETED')",
        ("date", "product", "category"),
        "public",
        "orders",
    ),
    MetricSeedItem(
        "order_count",
        "订单量",
        "单",
        "统计周期内创建的订单数量。",
        "COUNT(orders.id)",
        ("date", "product", "category", "order_status"),
        "public",
        "orders",
    ),
    MetricSeedItem(
        "paying_user_count",
        "付款用户数",
        "人",
        "统计周期内完成付款的去重用户数。",
        "COUNT(DISTINCT orders.buyer_key) WHERE paid_at IS NOT NULL",
        ("date", "product", "category"),
        "public",
        "orders",
    ),
    MetricSeedItem(
        "successful_order_count",
        "成功订单量",
        "单",
        "统计周期内交易成功的订单数量。",
        "COUNT(orders.id) WHERE order_status = 'COMPLETED'",
        ("date", "product", "category", "order_status"),
        "public",
        "orders",
    ),
    MetricSeedItem(
        "refund_count",
        "退款量",
        "单",
        "统计周期内发起退款的订单数量。",
        "COUNT(refunds.id) WHERE refund_status IN ('APPROVED','REFUNDED')",
        ("date", "refund_reason"),
        "public",
        "refunds",
    ),
    MetricSeedItem(
        "refund_amount",
        "退款金额",
        "元",
        "统计周期内退款总金额。",
        "SUM(refunds.refund_amount) WHERE refund_status = 'REFUNDED'",
        ("date", "refund_reason"),
        "public",
        "refunds",
    ),
    MetricSeedItem(
        "return_count",
        "退货量",
        "件",
        "统计周期内发起退货的商品件数。",
        "SUM(returns.return_quantity)",
        ("date", "return_reason", "return_status"),
        "public",
        "returns",
    ),
    MetricSeedItem(
        "return_rate",
        "退货率",
        "%",
        "退货件数除以同期订单项件数，按查询区间重新计算，不可跨日相加。",
        "SUM(returns.return_quantity) / NULLIF(SUM(order_items.quantity), 0)",
        ("date", "product", "category"),
        "public",
        "order_items",
    ),
    MetricSeedItem(
        "support_ticket_count",
        "客服工单量",
        "单",
        "统计周期内创建的客服工单数量。",
        "COUNT(support_tickets.id)",
        ("date", "ticket_status"),
        "public",
        "support_tickets",
    ),
)
