from __future__ import annotations

import pytest

from app.llm.client import STRUCTURED_CALL_OPTIONS, LlmBudget
from app.llm.fake import FakeLlmClient
from app.schemas.answer import AnswerDraft
from app.schemas.chat import Recommendation
from app.services.quality_types import AttemptFailureKind


def _draft() -> AnswerDraft:
    return AnswerDraft(
        answer="最近一天成交 GMV 为 12.00 元。",
        recommendations=[
            Recommendation(
                title="关注成交表现", evidence="成交 GMV 为 12.00 元。", action="继续观察。"
            ),
            Recommendation(title="核对范围", evidence="结果包含 1 行。", action="确认日期范围。"),
        ],
    )


async def _review(llm: FakeLlmClient):
    from app.services.review_service import ReviewService

    return await ReviewService().review_once(
        _draft(),
        "受控事实包",
        llm,
        LlmBudget(max_calls=4, max_tokens=1_000),
    )


@pytest.mark.asyncio
async def test_reviewer_returns_a_passed_verdict_without_rewriting_draft() -> None:
    llm = FakeLlmClient(responses=['```json\n{"passed":true,"issues":[]}\n```'])

    attempt = await _review(llm)

    assert attempt.verdict is not None
    assert attempt.verdict.passed is True
    assert attempt.issues == ()
    assert attempt.failure_kind is None
    assert llm.call_options == [STRUCTURED_CALL_OPTIONS]


@pytest.mark.asyncio
async def test_unavailable_reviewer_is_an_upstream_failure_not_a_rejection() -> None:
    """模型不可用与「复核判定不合格」必须分开：前者不该被回喂重写。"""

    attempt = await _review(FakeLlmClient(configured=False))

    assert attempt.verdict is None
    assert attempt.failure_kind is AttemptFailureKind.UPSTREAM


@pytest.mark.asyncio
async def test_transport_failure_is_an_upstream_failure() -> None:
    attempt = await _review(FakeLlmClient(behaviour="timeout"))

    assert attempt.verdict is None
    assert attempt.failure_kind is AttemptFailureKind.UPSTREAM


@pytest.mark.asyncio
async def test_invalid_reviewer_json_is_a_feedable_issue_not_an_outage() -> None:
    """Reviewer 输出非法 JSON 是一次不合格复核，循环应当回喂重试而不是直接降级。"""

    attempt = await _review(FakeLlmClient(behaviour="invalid_json"))

    assert attempt.verdict is None
    assert attempt.failure_kind is None
    assert any("无法解析" in issue for issue in attempt.issues)


@pytest.mark.asyncio
async def test_empty_reviewer_content_is_a_feedable_issue() -> None:
    attempt = await _review(FakeLlmClient(responses=[""]))

    assert attempt.verdict is None
    assert attempt.failure_kind is None
    assert any("为空" in issue for issue in attempt.issues)


@pytest.mark.asyncio
async def test_rejection_without_reasons_is_treated_as_an_unusable_output() -> None:
    """打回却不说哪里错，回喂时没有内容可回喂，只能当成不合格输出重试。"""

    attempt = await _review(FakeLlmClient(responses=['{"passed":false,"issues":[]}']))

    assert attempt.verdict is None
    assert attempt.failure_kind is None
    assert attempt.issues != ()


@pytest.mark.asyncio
async def test_passing_verdict_with_advisory_issues_is_normalized_not_rejected() -> None:
    """「通过，但建议补充同比」是模型很常见的形态。

    判成不合格会在 `QUALITY_MAX_ATTEMPTS=2` 下吃掉唯一一次重试机会，把一个已经
    通过复核的回答推向降级。改为归一化成 advisory 备注，对用户可见但不触发重试。
    """

    attempt = await _review(FakeLlmClient(responses=['{"passed":true,"issues":["建议补充同比"]}']))

    assert attempt.verdict is not None
    assert attempt.verdict.passed is True
    assert attempt.verdict.issues == []
    assert attempt.verdict.advisory_notes == ["建议补充同比"]
    assert attempt.issues == ()
