"""v2 规则检索的受控词汇扩展；不改变 v1 分词或知识事实。

多义词须同时满足业务上下文，英文按完整词匹配（不拆字段名）。
仅补充等价检索词，不生成答案、流程步骤或文档路径。
"""

from __future__ import annotations

import re

from app.agent.prefilter import tokenize

# 每条规则：必须同时命中的词组（组内任一），以及语料侧的等价词。
_RULES: tuple[tuple[tuple[tuple[str, ...], ...], tuple[str, ...]], ...] = (
    ((("赔偿",), ("买家", "商品", "东西", "货品", "订单")), ("理赔", "赔付")),
    ((("新品", "新款"), ("审核", "上架", "挂上去", "发布")), ("商品",)),
    ((("挂上去", "挂出去"), ("新品", "新款", "商品", "货品")), ("上架",)),
    (
        (("appeal", "appeals", "appealing"), ("penalty", "penalties", "punishment")),
        ("申诉", "处罚"),
    ),
    (
        (("coupon", "coupons", "voucher", "vouchers"), ("redemption", "redeem", "redeemed")),
        ("优惠券", "核销"),
    ),
    (
        (("coupon", "coupons", "voucher", "vouchers"), ("settlement", "settlements")),
        ("优惠券", "结算"),
    ),
)


def _contains(query: str, term: str) -> bool:
    if term.isascii():
        return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", query) is not None
    return term in query


def rule_query_terms(query: str) -> tuple[str, ...]:
    """保留原词及顺序；仅对有业务上下文的别名追加等价词并去重。"""

    normalized = query.casefold()
    additions = [
        term
        for groups, equivalents in _RULES
        if all(any(_contains(normalized, alias) for alias in group) for group in groups)
        for term in equivalents
    ]
    return tuple(dict.fromkeys((*tokenize(query), *additions)))
