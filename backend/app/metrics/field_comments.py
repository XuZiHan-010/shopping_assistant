"""受控字段注释口径。

PostgreSQL MVP 没有 Doris ``COLUMN_COMMENT``，因此把可用于二级降级的字段
注释显式登记为不可变白名单。这里的 SQL 说明均由后端维护，绝不接受模型或用户
输入作为标识符。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.analytics.contract import METRIC_SPECS


@dataclass(frozen=True)
class FieldCommentDefinition:
    metric_code: str
    business_definition: str
    sql_definition: str
    dimensions: tuple[str, ...]
    source_database: str
    source_table: str


FIELD_COMMENT_DEFINITIONS: Final[dict[str, FieldCommentDefinition]] = {
    "gmv": FieldCommentDefinition(
        "gmv",
        "已支付订单的实付金额。",
        "SUM(orders.paid_amount)",
        ("date", "product", "category"),
        "public",
        "orders",
    ),
    "order_count": FieldCommentDefinition(
        "order_count",
        "订单主键数量。",
        "COUNT(orders.id)",
        ("date", "product", "category", "order_status"),
        "public",
        "orders",
    ),
    "ordering_user_count": FieldCommentDefinition(
        "ordering_user_count",
        "统计周期内创建订单的去重买家数，不要求完成付款。",
        "COUNT(DISTINCT orders.buyer_key)",
        ("date", "product", "category"),
        "public",
        "orders",
    ),
    "paying_user_count": FieldCommentDefinition(
        "paying_user_count",
        "已付款订单中的去重买家数。",
        "COUNT(DISTINCT orders.buyer_key)",
        ("date", "product", "category"),
        "public",
        "orders",
    ),
    "successful_order_count": FieldCommentDefinition(
        "successful_order_count",
        "交易成功状态的订单数量。",
        "COUNT(orders.id) WHERE order_status = 'COMPLETED'",
        ("date", "product", "category", "order_status"),
        "public",
        "orders",
    ),
    "refund_count": FieldCommentDefinition(
        "refund_count",
        "退款记录数量。",
        "COUNT(refunds.id)",
        ("date", "refund_reason"),
        "public",
        "refunds",
    ),
    "refund_amount": FieldCommentDefinition(
        "refund_amount",
        "退款记录的退款金额。",
        "SUM(refunds.refund_amount)",
        ("date", "refund_reason"),
        "public",
        "refunds",
    ),
    "return_count": FieldCommentDefinition(
        "return_count",
        "退货记录的商品件数。",
        "SUM(returns.return_quantity)",
        ("date", "return_reason", "return_status"),
        "public",
        "returns",
    ),
    "return_rate": FieldCommentDefinition(
        "return_rate",
        "退货件数与订单项件数的比率。",
        "SUM(returns.return_quantity) / NULLIF(SUM(order_items.quantity), 0)",
        ("date", "product", "category"),
        "public",
        "order_items",
    ),
    "support_ticket_count": FieldCommentDefinition(
        "support_ticket_count",
        "客服工单记录数量。",
        "COUNT(support_tickets.id)",
        ("date", "ticket_status"),
        "public",
        "support_tickets",
    ),
}

assert set(FIELD_COMMENT_DEFINITIONS) == set(METRIC_SPECS)
assert all(
    definition.source_table == METRIC_SPECS[code].table
    for code, definition in FIELD_COMMENT_DEFINITIONS.items()
)


def find_field_comment(metric_code: str) -> FieldCommentDefinition | None:
    return FIELD_COMMENT_DEFINITIONS.get(metric_code)
