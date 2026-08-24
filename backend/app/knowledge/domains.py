"""业务域常量及 B4 安全查询的表路由。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.schemas.chat import QuestionCategory

MAX_KNOWLEDGE_CHARS: Final[int] = 24_000
MAX_PROMPT_KNOWLEDGE_CHARS: Final[int] = 10_000
INDEX_PATH_MARKERS: Final[tuple[str, ...]] = ("index", "rule", "目录")

#: 复合问法里的动作词与规则词。与 DOMAIN_KEYWORDS 的业务名词构成两张受控词表，
#: 「商品上架有哪些规则要求」据此拆成「商品（业务）+ 上架（动作）+ 规则（规则）」。
#:
#: 刻意**不引入分词器或向量库**（2026-08-22 用户裁定 D1）：拆词只在这两张已知词表里
#: 找子串，行为完全确定、可测试，也不新增依赖与模型调用。
#:
#: 词条与 DOMAIN_KEYWORDS 允许重叠（如「上架」同时是 GOODS 业务词与动作词），
#: 判定只要求「两张表各命中至少一个」，重叠不影响结论。
ACTION_RULE_TERMS: Final[tuple[str, ...]] = (
    "上架",
    "下架",
    "审核",
    "报名",
    "申请",
    "结算",
    "创建",
    "修改",
    "删除",
    "规则",
    "政策",
    "要求",
    "规范",
    "标准",
    "条件",
    "限制",
)

DOMAIN_KEYWORDS: Final[Mapping[QuestionCategory, tuple[str, ...]]] = {
    QuestionCategory.TRADE: ("交易", "订单", "成交", "履约", "支付", "trade", "order", "gmv"),
    QuestionCategory.REFUND: ("退货", "退款", "售后", "refund", "return"),
    QuestionCategory.CS_TICKET: ("客服", "工单", "咨询", "ticket"),
    QuestionCategory.COMPENSATION: ("理赔", "赔付", "补偿", "repay"),
    QuestionCategory.COUPON: ("优惠券", "优惠", "券", "coupon"),
    QuestionCategory.GOODS: ("商品", "货品", "上架", "goods", "spu"),
    QuestionCategory.MERCHANT_OTHER: ("保证金", "申诉", "处罚", "merchant"),
    QuestionCategory.IDENTITY: ("身份", "资料", "商家信息", "merchant"),
    QuestionCategory.SCM: ("供应链", "入库", "分拣", "质检", "鉴定", "出库", "仓库", "scm"),
    QuestionCategory.PLATFORM_RULE: ("规则", "政策", "平台要求", "rule"),
    QuestionCategory.UNKNOWN: ("通用",),
}

# B4 仅创建并允许查询以下经营数据表。退款与退货保持分表，不可替代。
DOMAIN_TABLES: Final[Mapping[QuestionCategory, tuple[str, ...]]] = {
    QuestionCategory.TRADE: ("orders", "order_items"),
    QuestionCategory.REFUND: ("refunds", "returns"),
    QuestionCategory.CS_TICKET: ("support_tickets",),
    QuestionCategory.COMPENSATION: (),
    QuestionCategory.COUPON: (),
    QuestionCategory.GOODS: ("products",),
    QuestionCategory.MERCHANT_OTHER: (),
    QuestionCategory.IDENTITY: (),
    QuestionCategory.SCM: (),
    QuestionCategory.PLATFORM_RULE: (),
    QuestionCategory.UNKNOWN: (),
}


def merchant_filter_key(category: QuestionCategory) -> str:
    """B4 的每张经营表均以 merchant_id 作为强制商家隔离列。"""

    del category
    return "merchant_id"
