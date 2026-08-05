"""指标与维度到数据库对象的唯一映射。

**用户输入永远不进入 SQL 的标识符位置。** 模型和用户只能给出 metric_code 与
dimension 名，能不能落到某张表某一列，完全由这张代码内注册表决定。B3 的意图
白名单是第一道，这里是第二道——计划把「查询层必须再校验一次」写成了硬要求。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

MetricKind = Literal["SIMPLE", "RATIO"]


class UnknownFieldError(LookupError):
    """请求了注册表之外的指标或维度。调用方应转成可展示的拒绝原因。"""


@dataclass(frozen=True)
class MetricSpec:
    code: str
    label: str
    unit: str
    #: 主表。RATIO 类指标的主表是分母所在表。
    table: str
    #: 能否跨区间相加。去重计数与比例为 False。
    additive: bool
    kind: MetricKind = "SIMPLE"


@dataclass(frozen=True)
class DimensionSpec:
    code: str
    label: str
    table: str
    column: str


METRIC_SPECS: Final[Mapping[str, MetricSpec]] = {
    "gmv": MetricSpec("gmv", "成交 GMV", "元", "orders", True),
    "order_count": MetricSpec("order_count", "订单量", "单", "orders", True),
    "paying_user_count": MetricSpec("paying_user_count", "付款用户数", "人", "orders", False),
    "successful_order_count": MetricSpec(
        "successful_order_count", "成功订单量", "单", "orders", True
    ),
    "refund_count": MetricSpec("refund_count", "退款量", "单", "refunds", True),
    "refund_amount": MetricSpec("refund_amount", "退款金额", "元", "refunds", True),
    "return_count": MetricSpec("return_count", "退货量", "件", "returns", True),
    "return_rate": MetricSpec("return_rate", "退货率", "%", "order_items", False, "RATIO"),
    "support_ticket_count": MetricSpec(
        "support_ticket_count", "客服工单量", "单", "support_tickets", True
    ),
}

DIMENSION_SPECS: Final[Mapping[str, DimensionSpec]] = {
    "date": DimensionSpec("date", "日期", "", "business_date"),
    "product": DimensionSpec("product", "商品", "products", "title"),
    "category": DimensionSpec("category", "类目", "products", "category"),
    "order_status": DimensionSpec("order_status", "订单状态", "orders", "order_status"),
    "refund_reason": DimensionSpec("refund_reason", "退款原因", "refunds", "refund_reason"),
    "return_reason": DimensionSpec("return_reason", "退货原因", "returns", "return_reason"),
    "return_status": DimensionSpec("return_status", "退货状态", "returns", "return_status"),
    "ticket_status": DimensionSpec("ticket_status", "工单状态", "support_tickets", "ticket_status"),
}

#: 每张主表能连到哪些维度表。空字符串代表「用主表自己的列」（date）。
_COMPATIBLE: Final[Mapping[str, frozenset[str]]] = {
    "orders": frozenset({"", "orders", "products"}),
    "refunds": frozenset({"", "refunds"}),
    "returns": frozenset({"", "returns"}),
    "order_items": frozenset({"", "products"}),
    "support_tickets": frozenset({"", "support_tickets"}),
}


def metric_spec(code: str) -> MetricSpec:
    try:
        return METRIC_SPECS[code]
    except KeyError as error:
        raise UnknownFieldError(f"指标 {code} 不在受控查询契约内") from error


def dimension_spec(code: str) -> DimensionSpec:
    try:
        return DIMENSION_SPECS[code]
    except KeyError as error:
        raise UnknownFieldError(f"维度 {code} 不在受控查询契约内") from error


def compatible_dimensions(metric: MetricSpec) -> frozenset[str]:
    """该指标可用的维度集合。不兼容的组合由调用方显式拒绝，不静默忽略。"""

    tables = _COMPATIBLE[metric.table]
    return frozenset(code for code, spec in DIMENSION_SPECS.items() if spec.table in tables)
