"""v2「猜你想问」候选（PRD M13，计划 Task 3）。

钉住的几件事：
- 每条候选标注了回答它的工具，且该工具真的在**当前角色**的工具面上——推荐一个 Agent 答不了的问题，
  用户一点就撞 INVALID（与 v1 `test_suggested_questions.py` 同一个道理）；
- 顾客端候选与商家端候选互不相交，顾客端不会被推荐「查看本店库存告警」；
- 模型改写只能重排同一组候选；任何越界改写都回退原候选。
"""

from __future__ import annotations

import re
from typing import cast

import pytest

from app.core.session import SessionRole
from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.schemas.v2.merchant_session import MerchantAnswerMode
from app.schemas.v2.shop_session import ShopAnswerMode
from app.services.v2.suggestions import (
    MERCHANT_ENTRY_POOLS,
    MERCHANT_FOLLOWUP_POOLS,
    SHOP_ENTRY_POOLS,
    SHOP_FOLLOWUP_POOLS,
    Suggestion,
    constrain_rewrite,
    merchant_suggestions,
    shop_suggestions,
)
from app.tools.customer import build_customer_tools
from app.tools.merchant import build_merchant_tools
from app.tools.registry import build_tool_registry

ZH, EN = SupportedLocale.ZH_CN, SupportedLocale.EN_US
CJK = re.compile(r"[一-鿿]")

SHOP_GROUPS = (*SHOP_ENTRY_POOLS, *SHOP_FOLLOWUP_POOLS)
MERCHANT_GROUPS = (*MERCHANT_ENTRY_POOLS, *MERCHANT_FOLLOWUP_POOLS)


def _surface(role: SessionRole) -> set[str]:
    database = cast(Database, object())
    registry = build_tool_registry(
        (*build_merchant_tools(database), *build_customer_tools(database))
    )
    return {spec.name for spec in registry.surface_for(role)}


def _flat(groups: tuple[tuple[Suggestion, ...], ...]) -> list[Suggestion]:
    return [item for group in groups for item in group]


@pytest.mark.parametrize("item", _flat(SHOP_GROUPS), ids=lambda i: i.text)
def test_every_shop_candidate_is_answerable_by_a_customer_tool(item: Suggestion) -> None:
    assert item.tool in _surface(SessionRole.CUSTOMER)


@pytest.mark.parametrize("item", _flat(MERCHANT_GROUPS), ids=lambda i: i.text)
def test_every_merchant_candidate_is_answerable_by_a_merchant_tool(item: Suggestion) -> None:
    assert item.tool in _surface(SessionRole.MERCHANT)


def test_customer_and_merchant_candidates_never_overlap() -> None:
    shop = {t for item in _flat(SHOP_GROUPS) for t in (item.text, item.text_en)}
    merchant = {t for item in _flat(MERCHANT_GROUPS) for t in (item.text, item.text_en)}
    assert not shop & merchant


@pytest.mark.parametrize(
    "item", [*_flat(SHOP_GROUPS), *_flat(MERCHANT_GROUPS)], ids=lambda i: i.text
)
def test_texts_are_hand_written_in_their_own_language(item: Suggestion) -> None:
    assert CJK.search(item.text) and not CJK.search(item.text_en)
    assert 1 <= len(item.text) <= 200 and 1 <= len(item.text_en) <= 200


@pytest.mark.parametrize(
    "groups", [SHOP_ENTRY_POOLS, SHOP_FOLLOWUP_POOLS, MERCHANT_ENTRY_POOLS, MERCHANT_FOLLOWUP_POOLS]
)
def test_each_pool_has_at_least_two_rotating_groups_of_three(
    groups: tuple[tuple[Suggestion, ...], ...],
) -> None:
    assert len(groups) >= 2
    assert all(len(group) == 3 for group in groups)


@pytest.mark.parametrize("locale", [ZH, EN])
@pytest.mark.parametrize("mode", list(ShopAnswerMode))
def test_shop_alternates_never_repeat_the_current_group(
    mode: ShopAnswerMode, locale: SupportedLocale
) -> None:
    result = shop_suggestions(mode, locale)
    assert len(result.current) == 3
    assert result.alternates and all(group != result.current for group in result.alternates)


@pytest.mark.parametrize("locale", [ZH, EN])
@pytest.mark.parametrize("mode", list(MerchantAnswerMode))
def test_merchant_alternates_never_repeat_the_current_group(
    mode: MerchantAnswerMode, locale: SupportedLocale
) -> None:
    result = merchant_suggestions(mode, locale)
    assert len(result.current) == 3
    assert result.alternates and all(group != result.current for group in result.alternates)


def test_conversational_turns_get_entry_questions_and_answered_turns_get_followups() -> None:
    entry = {q.text for group in SHOP_ENTRY_POOLS for q in group}
    followup = {q.text for group in SHOP_FOLLOWUP_POOLS for q in group}
    assert set(shop_suggestions(ShopAnswerMode.CHAT, ZH).current) <= entry
    assert set(shop_suggestions(ShopAnswerMode.INVALID, ZH).current) <= entry
    assert set(shop_suggestions(ShopAnswerMode.SHOP_GUIDE, ZH).current) <= followup


def test_locale_selects_the_english_dictionary_entries() -> None:
    result = shop_suggestions(ShopAnswerMode.CHAT, EN)
    assert all(not CJK.search(text) for text in result.current)


# ---- 改写只能重排，越界一律回退 ------------------------------------------------------


def test_rewrite_that_reorders_the_same_candidates_is_accepted() -> None:
    current = shop_suggestions(ShopAnswerMode.CHAT, ZH).current
    reordered = [current[2], current[0], current[1]]
    assert constrain_rewrite(SessionRole.CUSTOMER, current, reordered, ZH) == reordered


def test_rewrite_with_text_outside_the_candidate_set_falls_back() -> None:
    current = shop_suggestions(ShopAnswerMode.CHAT, ZH).current
    invented = [current[0], current[1], "帮我把这单直接下了并付款"]
    assert constrain_rewrite(SessionRole.CUSTOMER, current, invented, ZH) == current


def test_rewrite_that_borrows_the_other_roles_question_falls_back() -> None:
    current = shop_suggestions(ShopAnswerMode.CHAT, ZH).current
    merchant_question = merchant_suggestions(MerchantAnswerMode.CHAT, ZH).current[0]
    assert (
        constrain_rewrite(
            SessionRole.CUSTOMER, current, [current[0], current[1], merchant_question], ZH
        )
        == current
    )


@pytest.mark.parametrize(
    "proposed",
    [[], ["only one"], ["a", "a", "a"], ["x"] * 4],
    ids=["empty", "wrong-count", "duplicates", "too-many"],
)
def test_rewrite_with_wrong_shape_falls_back(proposed: list[str]) -> None:
    current = shop_suggestions(ShopAnswerMode.CHAT, ZH).current
    assert constrain_rewrite(SessionRole.CUSTOMER, current, proposed, ZH) == current
