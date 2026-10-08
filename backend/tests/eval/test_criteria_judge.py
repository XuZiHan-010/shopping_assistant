"""逐项判定 + 多票中位数的 LLM 裁判（E2）。

2026-10-06 真实评测里，只输出一个小数、只判一次的旧裁判对同一句正确回答
先后给出 1.0 / 0.5 / 0.4（及格线 0.6）。这里的用例各自钉住一个会让那种
不稳定重新出现的改动。
"""

from __future__ import annotations

import json

from app.eval.graders.criteria_judge import CriteriaRubric, Criterion, grade_by_criteria
from app.llm.fake import FakeLlmClient

RUBRIC = CriteriaRubric(
    id="answer_quality",
    version="test-v1",
    criteria=(
        Criterion(key="responsive", description="直接回应了提问"),
        Criterion(key="language", description="自然语言与显示语言一致"),
    ),
)
TRANSCRIPT = "[显示语言 zh-CN]\n用户：最近7天退款金额\n助手：最近7天的退款金额为 4293.00 元。"


def _vote(responsive: bool, language: bool) -> str:
    return json.dumps(
        {
            "responsive": {"passed": responsive, "reason": "理由甲"},
            "language": {"passed": language, "reason": "理由乙"},
        },
        ensure_ascii=False,
    )


async def test_one_dissenting_vote_does_not_flip_a_passing_answer() -> None:
    judge = FakeLlmClient(responses=[_vote(True, True), _vote(True, False), _vote(True, True)])

    result = await grade_by_criteria(client=judge, rubric=RUBRIC, transcript=TRANSCRIPT)

    assert [vote.score for vote in result.votes] == [1.0, 0.5, 1.0]
    assert result.score == 1.0
    assert result.passed is True
    assert result.unanimous is False


async def test_answer_fails_when_most_votes_find_an_unmet_criterion() -> None:
    judge = FakeLlmClient(responses=[_vote(True, False), _vote(True, True), _vote(True, False)])

    result = await grade_by_criteria(client=judge, rubric=RUBRIC, transcript=TRANSCRIPT)

    assert result.score == 0.5
    assert result.passed is False
    assert result.votes[0].reasons == {"responsive": "理由甲", "language": "理由乙"}
    assert result.votes[0].verdicts == {"responsive": True, "language": False}


async def test_unparseable_vote_is_set_aside_instead_of_scored_zero() -> None:
    judge = FakeLlmClient(responses=["我认为很好", _vote(True, True), _vote(True, True)])

    result = await grade_by_criteria(client=judge, rubric=RUBRIC, transcript=TRANSCRIPT)

    assert result.votes[0].score is None
    assert result.votes[0].raw_response == "我认为很好"
    assert result.score == 1.0
    assert result.passed is True


async def test_vote_missing_a_criterion_is_invalid_not_assumed_passed() -> None:
    partial = json.dumps({"responsive": {"passed": True, "reason": "只判了一项"}})
    truthy_string = json.dumps(
        {
            "responsive": {"passed": "true", "reason": "字符串不是布尔"},
            "language": {"passed": True, "reason": "正常"},
        }
    )
    judge = FakeLlmClient(responses=[partial, truthy_string, _vote(True, True)])

    result = await grade_by_criteria(client=judge, rubric=RUBRIC, transcript=TRANSCRIPT)

    assert [vote.score for vote in result.votes] == [None, None, 1.0]


async def test_no_usable_vote_is_inconclusive_and_never_passes() -> None:
    judge = FakeLlmClient(responses=["x", "y", "z"])

    result = await grade_by_criteria(client=judge, rubric=RUBRIC, transcript=TRANSCRIPT)

    assert result.score is None
    assert result.passed is False


async def test_each_vote_is_a_separate_structured_call_carrying_rubric_and_transcript() -> None:
    judge = FakeLlmClient(responses=[_vote(True, True)] * 3)

    result = await grade_by_criteria(client=judge, rubric=RUBRIC, transcript=TRANSCRIPT)

    assert len(judge.calls) == 3
    assert result.rubric_id == "answer_quality"
    assert result.rubric_version == "test-v1"
    for system, user in judge.calls:
        assert "answer_quality@test-v1" in system
        assert "responsive" in user and "直接回应了提问" in user
        assert "language" in user and "自然语言与显示语言一致" in user
        assert TRANSCRIPT in user
    assert all(options.json_output for options in judge.call_options)
    assert all(options.thinking == "disabled" for options in judge.call_options)
