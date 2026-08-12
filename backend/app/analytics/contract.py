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


@dataclass(frozen=True)
class DetailSpec:
    table: str
    label: str
    #: (列名, 中文标签) 的有序元组。顺序即展示顺序；显式列举也是「禁止 SELECT *」的落点。
    columns: tuple[tuple[str, str], ...]
    #: 这张表的 `business_date` 是不是「业务事件发生日」，决定明细查询要不要
    #: 按查询区间过滤它。
    #:
    #: 事件表（订单、退款、退货、工单）为真：一行就是某一天发生的一件事，
    #: 「最近 7 天的订单」理应只看那 7 天。维度表为假：`products.business_date`
    #: 是**上架日**，商品一旦上架就一直存在，按查询区间过滤会让「看看我的商品
    #: 明细」只返回窗口内恰好上架的那一两个，其余被静默丢掉——商家看不到自己
    #: 大部分商品，也没有任何提示。
    #:
    #: 放在契约层而不是让服务层特判某张表：这是「这张表的时间语义是什么」的
    #: 声明，和列名、标签一样属于表本身的性质，不是调用方的临时决定。
    date_filtered: bool = True


DETAIL_SPECS: Final[Mapping[str, DetailSpec]] = {
    "orders": DetailSpec(
        "orders",
        "订单明细",
        (
            ("business_date", "日期"),
            ("order_no", "订单号"),
            ("order_status", "订单状态"),
            ("paid_amount", "实付金额"),
            ("placed_at", "下单时间"),
        ),
    ),
    "refunds": DetailSpec(
        "refunds",
        "退款明细",
        (
            ("business_date", "日期"),
            ("refund_amount", "退款金额"),
            ("refund_reason", "退款原因"),
            ("refund_status", "退款状态"),
            ("refunded_at", "退款时间"),
        ),
    ),
    "returns": DetailSpec(
        "returns",
        "退货明细",
        (
            ("business_date", "日期"),
            ("return_quantity", "退货件数"),
            ("return_reason", "退货原因"),
            ("return_status", "退货状态"),
            ("logistics_status", "物流状态"),
        ),
    ),
    "products": DetailSpec(
        "products",
        "商品明细",
        (
            ("business_date", "上架日"),
            ("product_code", "商品编码"),
            ("title", "商品名称"),
            ("category", "类目"),
            ("price", "价格"),
            ("status", "状态"),
        ),
        # 商品是维度表：`business_date` 是上架日，不是业务事件日。见 DetailSpec.date_filtered。
        date_filtered=False,
    ),
    "support_tickets": DetailSpec(
        "support_tickets",
        "工单明细",
        (
            ("business_date", "日期"),
            ("ticket_no", "工单号"),
            ("ticket_status", "工单状态"),
            ("ticket_reason", "工单类型"),
            ("opened_at", "创建时间"),
        ),
    ),
}

#: 业务分类到默认明细表的路由。没有对应经营表的域不出现在这里。
#:
#: `REFUND` 这一级本身是模糊的：退款（资金动作）与退货（货品动作）在 PRD 里
#: 明确是两件可以分开发生的事，但 B3 的分类粒度只到 `REFUND` 这一级，两者
#: 都挂在同一个分类下。这里维持"退款"作为兜底，真正的二次判定（按维度/筛选
#: 字段、再按关键词分流到 `returns`）由 `app.services.safe_query` 完成——
#: 那里离意图和查询上下文更近，这张表只负责"分类拿不到更多信号时查什么"。
DETAIL_BY_CATEGORY: Final[Mapping[str, str]] = {
    "TRADE": "orders",
    "REFUND": "refunds",
    "CS_TICKET": "support_tickets",
    "GOODS": "products",
}

#: `REFUND` 分类下用关键词二次判定该查 `returns`（退货）还是 `refunds`
#: （退款）——出现子串就足以判定，不需要完整分词。词表是不可变契约的一部分，
#: 不下放到服务层，避免同一个判断标准散落在多处、后续改一处漏一处。
REFUND_CATEGORY_RETURN_KEYWORDS: Final[frozenset[str]] = frozenset({"退货", "退回"})
REFUND_CATEGORY_REFUND_KEYWORDS: Final[frozenset[str]] = frozenset({"退款"})


def detail_spec(table: str) -> DetailSpec:
    try:
        return DETAIL_SPECS[table]
    except KeyError as error:
        raise UnknownFieldError(f"明细 {table} 不在受控查询契约内") from error
