"""服务端预置的「猜你想问」。

结构 1:1 对齐 `yshopping-prototype/app.js`：

- **当前组**是场景自带的追问（`scenarios.*.suggestions`），随回答一起返回；
- **备选组**是与场景无关的全局轮换池（`followupPools`），共 3 组，
  前端点「换一换」在这 3 组之间循环，不发额外请求；
- 空状态（还没提问）展示第一组。
"""

from __future__ import annotations

from dataclasses import dataclass

QuestionGroup = tuple[str, str, str]


@dataclass(frozen=True)
class SuggestedQuestions:
    current: list[str]
    alternates: list[list[str]]


# 逐字对照 yshopping-prototype/app.js:157-161，顺序即「换一换」的循环顺序。
FOLLOWUP_POOLS: tuple[QuestionGroup, ...] = (
    ("我想查看保证金", "最近7天咨询工单量", "我要货品上架，具体规则有吗？"),
    ("昨天总 GMV 是多少？", "最近7天退货量趋势", "查看优惠券明细"),
    ("查看商品上架明细", "昨天退款金额是多少？", "我的商家手机号是多少？"),
)


def _copy_pools() -> list[list[str]]:
    return [list(pool) for pool in FOLLOWUP_POOLS]


def initial_suggestions() -> list[str]:
    """空状态展示的问题组（app.js:110）。"""

    return list(FOLLOWUP_POOLS[0])


def pick(scenario_suggestions: list[str]) -> SuggestedQuestions:
    """把场景自带追问包装成响应字段，并附上全局轮换池。"""

    return SuggestedQuestions(current=list(scenario_suggestions), alternates=_copy_pools())
