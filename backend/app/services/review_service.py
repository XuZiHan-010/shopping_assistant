"""独立审核候选回答；Reviewer 从不改写回答。"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.client import (
    LlmBudget,
    LlmBudgetError,
    LlmClient,
    LlmDailyBudgetExceededError,
    LlmUnavailableError,
)
from app.prompts.reviewer import REVIEWER_SYSTEM_PROMPT
from app.schemas.answer import AnswerDraft, ReviewVerdict


@dataclass(frozen=True)
class ReviewResult:
    verdict: ReviewVerdict
    degraded: bool
    notes: list[str]


class ReviewService:
    async def review(
        self,
        draft: AnswerDraft,
        facts_json: str,
        llm: LlmClient,
        budget: LlmBudget,
    ) -> ReviewResult:
        try:
            result = await llm.complete(
                system=REVIEWER_SYSTEM_PROMPT,
                user=('{"facts":' + facts_json + ',"candidate":' + draft.model_dump_json() + "}"),
                fallback='{"passed":false,"issues":["Reviewer 暂不可用"]}',
                budget=budget,
            )
            if result.degraded:
                return _degraded_result()
            return ReviewResult(
                verdict=ReviewVerdict.model_validate_json(result.text),
                degraded=False,
                notes=[],
            )
        except LlmDailyBudgetExceededError:
            return ReviewResult(
                verdict=ReviewVerdict(passed=False, issues=["今日模型用量已达上限"]),
                degraded=True,
                notes=["今日模型用量已达上限，本次只提供受控数据摘要"],
            )
        except (ValueError, LlmUnavailableError, LlmBudgetError):
            return _degraded_result()


def _degraded_result() -> ReviewResult:
    return ReviewResult(
        verdict=ReviewVerdict(passed=False, issues=["Reviewer 暂不可用"]),
        degraded=True,
        notes=["Reviewer 暂不可用，已显示受控数据摘要。"],
    )
