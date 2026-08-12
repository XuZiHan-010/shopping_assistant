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
    source: str = "Borough 指标目录"
    owner: str = "经营分析组"


METRIC_SEED: Final[tuple[MetricSeedItem, ...]] = (
    MetricSeedItem(
        "gmv",
        "成交 GMV",
        "元",
        "统计周期内已支付订单金额之和。",
        "SUM(orders.paid_amount) WHERE order_status IN ('PAID','SHIPPED','COMPLETED')",
    ),
    MetricSeedItem("order_count", "订单量", "单", "统计周期内创建的订单数量。", "COUNT(orders.id)"),
    MetricSeedItem(
        "paying_user_count",
        "付款用户数",
        "人",
        "统计周期内完成付款的去重用户数。",
        "COUNT(DISTINCT orders.buyer_key) WHERE paid_at IS NOT NULL",
    ),
    MetricSeedItem(
        "successful_order_count",
        "成功订单量",
        "单",
        "统计周期内交易成功的订单数量。",
        "COUNT(orders.id) WHERE order_status = 'COMPLETED'",
    ),
    MetricSeedItem(
        "refund_count",
        "退款量",
        "单",
        "统计周期内发起退款的订单数量。",
        "COUNT(refunds.id) WHERE refund_status IN ('APPROVED','REFUNDED')",
    ),
    MetricSeedItem(
        "refund_amount",
        "退款金额",
        "元",
        "统计周期内退款总金额。",
        "SUM(refunds.refund_amount) WHERE refund_status = 'REFUNDED'",
    ),
    MetricSeedItem(
        "return_count",
        "退货量",
        "件",
        "统计周期内发起退货的商品件数。",
        "SUM(returns.return_quantity)",
    ),
    MetricSeedItem(
        "return_rate",
        "退货率",
        "%",
        "退货件数除以同期订单项件数，按查询区间重新计算，不可跨日相加。",
        "SUM(returns.return_quantity) / NULLIF(SUM(order_items.quantity), 0)",
    ),
    MetricSeedItem(
        "support_ticket_count",
        "客服工单量",
        "单",
        "统计周期内创建的客服工单数量。",
        "COUNT(support_tickets.id)",
    ),
)
