"""预置推荐问题测试。

除了结构（每域两组、每组三条、「换一换」不重复当前组），这里还钉住 §6.8 的必测项：
**所有预置问题都要能通过 Intent 白名单校验**。推荐一个白名单外的问题，用户点一下
就撞 `INVALID`，而这类回归在运行时是静默的。
"""

import pytest

from app.intent.whitelist import DIMENSION_WHITELIST, METRIC_WHITELIST
from app.knowledge.domains import DOMAIN_TABLES
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services.suggested_questions import (
    DOMAIN_FOLLOWUP_POOLS,
    FOLLOWUP_POOLS,
    PresetQuestion,
    QuestionKind,
    initial_suggestions,
    pick,
    suggestions_for,
)

ALL_GROUPS = [
    *FOLLOWUP_POOLS,
    *[group for pools in DOMAIN_FOLLOWUP_POOLS.values() for group in pools],
]
ALL_QUESTIONS = [question for group in ALL_GROUPS for question in group]

#: B4 第一批明细可路由的经营表。
DETAIL_TABLES = {table for tables in DOMAIN_TABLES.values() for table in tables}


@pytest.mark.parametrize("question", ALL_QUESTIONS, ids=lambda q: q.text)
def test_data_questions_stay_inside_the_intent_whitelists(question: PresetQuestion) -> None:
    """数据型推荐问题落在白名单外，用户点击后只会拿到 INVALID。"""

    if question.kind is not QuestionKind.DATA:
        return

    assert question.metric is not None or question.dimensions or question.detail is not None
    if question.metric is not None:
        assert question.metric in METRIC_WHITELIST
    assert set(question.dimensions) <= DIMENSION_WHITELIST
    if question.detail is not None:
        assert question.detail in DETAIL_TABLES


@pytest.mark.parametrize("question", ALL_QUESTIONS, ids=lambda q: q.text)
def test_non_data_questions_declare_no_query_fields(question: PresetQuestion) -> None:
    """知识和身份问题带上指标标注，会让白名单校验形同虚设。"""

    if question.kind is QuestionKind.DATA:
        return

    assert question.metric is None
    assert question.dimensions == ()
    assert question.detail is None


def test_chat_entry_group_shows_all_three_answer_paths() -> None:
    """入门组要让新用户看到助手能做什么，只推一类问题会缩小认知。"""

    kinds = {question.kind for group in FOLLOWUP_POOLS for question in group}

    assert kinds == {QuestionKind.DATA, QuestionKind.KNOWLEDGE, QuestionKind.IDENTITY}


def test_empty_state_uses_the_first_pool() -> None:
    assert initial_suggestions() == [question.text for question in FOLLOWUP_POOLS[0]]


def test_current_group_comes_from_the_scenario() -> None:
    result = pick(DOMAIN_FOLLOWUP_POOLS[QuestionCategory.REFUND][0])

    assert result.current == [
        question.text for question in DOMAIN_FOLLOWUP_POOLS[QuestionCategory.REFUND][0]
    ]


def test_alternates_exclude_the_current_group() -> None:
    refund = DOMAIN_FOLLOWUP_POOLS[QuestionCategory.REFUND][0]

    result = pick(refund, candidate_groups=(refund, FOLLOWUP_POOLS[0]))

    assert result.alternates == [[question.text for question in FOLLOWUP_POOLS[0]]]


@pytest.mark.parametrize("group", ALL_GROUPS, ids=lambda g: g[0].text)
def test_every_group_offers_exactly_three_questions(group: tuple[PresetQuestion, ...]) -> None:
    assert len(group) == 3


def test_pick_returns_copies_that_callers_cannot_mutate_into_the_config() -> None:
    result = pick(FOLLOWUP_POOLS[0])
    result.alternates[0].append("被污染的问题")

    assert len(pick(FOLLOWUP_POOLS[0]).alternates[0]) == 3


def test_initial_suggestions_returns_a_copy() -> None:
    initial_suggestions().append("被污染的问题")

    assert len(initial_suggestions()) == 3


@pytest.mark.parametrize("category", list(QuestionCategory))
def test_every_domain_has_two_or_more_followup_groups(category: QuestionCategory) -> None:
    pools = DOMAIN_FOLLOWUP_POOLS[category]

    assert len(pools) >= 2
    assert all(len(pool) == 3 for pool in pools)


@pytest.mark.parametrize("category", list(QuestionCategory))
def test_non_chat_suggestions_are_domain_specific_and_rotatable(category: QuestionCategory) -> None:
    result = suggestions_for(category, AnswerMode.RULE)
    pools = DOMAIN_FOLLOWUP_POOLS[category]

    assert result.current == [question.text for question in pools[0]]
    assert result.alternates == [[question.text for question in pool] for pool in pools[1:]]
    assert result.current not in result.alternates


def test_chat_suggestions_keep_the_introductory_group() -> None:
    result = suggestions_for(QuestionCategory.TRADE, AnswerMode.CHAT)

    assert result.current == initial_suggestions()
    assert result.alternates == [
        [question.text for question in pool] for pool in FOLLOWUP_POOLS[1:]
    ]
