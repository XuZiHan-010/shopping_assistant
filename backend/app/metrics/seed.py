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


def _item(code: str, name: str, unit: str, definition: str) -> MetricSeedItem:
    return MetricSeedItem(code, name, unit, definition, f"SUM({code})")


METRIC_SEED: Final[tuple[MetricSeedItem, ...]] = (
    _item("gmv", "成交 GMV", "元", "统计周期内已支付订单金额之和。"),
    _item("order_count", "订单量", "单", "统计周期内创建的订单数量。"),
    _item("paying_user_count", "付款用户数", "人", "统计周期内完成付款的去重用户数。"),
    _item("successful_order_count", "成功订单量", "单", "统计周期内交易成功的订单数量。"),
    _item("refund_count", "退款量", "单", "统计周期内发起退款的订单数量。"),
    _item("refund_amount", "退款金额", "元", "统计周期内退款总金额。"),
    _item("return_count", "退货量", "件", "统计周期内发起退货的商品件数。"),
    _item("return_rate", "退货率", "%", "退货件数除以同期订单项件数，按查询区间重新计算。"),
    _item("support_ticket_count", "客服工单量", "单", "统计周期内创建的客服工单数量。"),
)
