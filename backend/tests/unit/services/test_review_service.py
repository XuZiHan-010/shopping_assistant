from __future__ import annotations

import pytest

from app.llm.client import LlmBudget
from app.llm.fake import FakeLlmClient
from app.schemas.answer import AnswerDraft
from app.schemas.chat import Recommendation


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


@pytest.mark.asyncio
async def test_reviewer_returns_a_passed_verdict_without_rewriting_draft() -> None:
    from app.services.review_service import ReviewService

    result = await ReviewService().review(
        _draft(),
        "受控事实包",
        FakeLlmClient(responses=['{"passed":true,"issues":[]}']),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.verdict.passed is True
    assert result.verdict.issues == []
    assert result.degraded is False


@pytest.mark.asyncio
async def test_reviewer_marks_unavailable_model_as_degraded() -> None:
    from app.services.review_service import ReviewService

    result = await ReviewService().review(
        _draft(),
        "受控事实包",
        FakeLlmClient(configured=False),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.verdict.passed is False
    assert result.degraded is True
    assert result.notes == ["Reviewer 暂不可用，已显示受控数据摘要。"]


@pytest.mark.asyncio
async def test_reviewer_treats_invalid_json_as_degraded() -> None:
    from app.services.review_service import ReviewService

    result = await ReviewService().review(
        _draft(),
        "受控事实包",
        FakeLlmClient(behaviour="invalid_json"),
        LlmBudget(max_calls=4, max_tokens=1_000),
    )

    assert result.verdict.passed is False
    assert result.degraded is True
