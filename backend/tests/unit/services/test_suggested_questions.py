"""预置推荐问题测试。

结构 1:1 对齐 `yshopping-prototype/app.js`：当前组来自场景自带的 `suggestions`，
备选组是与场景无关的全局 `followupPools`，「换一换」在这 3 组之间循环。
"""

import pytest

from app.services.suggested_questions import (
    FOLLOWUP_POOLS,
    initial_suggestions,
    pick,
)

# 逐字对照 yshopping-prototype/app.js:157-161。
PROTOTYPE_POOLS = [
    ["我想查看保证金", "最近7天咨询工单量", "我要货品上架，具体规则有吗？"],
    ["昨天总 GMV 是多少？", "最近7天退货量趋势", "查看优惠券明细"],
    ["查看商品上架明细", "昨天退款金额是多少？", "我的商家手机号是多少？"],
]

REFUND_SUGGESTIONS = [
    "按商品查看退货量排行",
    "这些退货的主要原因是什么？",
    "导出最近7天退货明细",
]


def test_pools_match_the_prototype() -> None:
    assert [list(pool) for pool in FOLLOWUP_POOLS] == PROTOTYPE_POOLS


def test_empty_state_uses_the_first_pool() -> None:
    """还没提问时，原型展示 followupPools[0]（app.js:110）。"""

    assert PROTOTYPE_POOLS[0] == initial_suggestions()


def test_current_group_comes_from_the_scenario() -> None:
    result = pick(REFUND_SUGGESTIONS)

    assert result.current == REFUND_SUGGESTIONS


def test_alternates_are_the_global_pools_regardless_of_scenario() -> None:
    refund = pick(REFUND_SUGGESTIONS)
    rule = pick(["我的商品为什么审核不通过？", "查看商品上架明细", "哪些类目需要特殊资质？"])

    assert refund.alternates == PROTOTYPE_POOLS
    assert rule.alternates == PROTOTYPE_POOLS


@pytest.mark.parametrize("pool", PROTOTYPE_POOLS)
def test_every_pool_offers_exactly_three_questions(pool: list[str]) -> None:
    assert len(pool) == 3


def test_pick_returns_copies_that_callers_cannot_mutate_into_the_config() -> None:
    result = pick(REFUND_SUGGESTIONS)
    result.alternates[0].append("被污染的问题")

    assert len(pick(REFUND_SUGGESTIONS).alternates[0]) == 3


def test_initial_suggestions_returns_a_copy() -> None:
    initial_suggestions().append("被污染的问题")

    assert len(initial_suggestions()) == 3
