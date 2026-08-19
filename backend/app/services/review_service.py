"""独立审核候选回答；Reviewer 从不改写回答。"""

from __future__ import annotations

from app.llm.client import (
    STRUCTURED_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetError,
    LlmClient,
    LlmUnavailableError,
)
from app.prompts.reviewer import REVIEWER_SYSTEM_PROMPT
from app.schemas.answer import AnswerDraft, ReviewVerdict
from app.services.answer_service import extract_json_object
from app.services.quality_types import AttemptFailureKind, ReviewAttempt


class ReviewService:
    async def review_once(
        self,
        draft: AnswerDraft,
        facts_json: str,
        llm: LlmClient,
        budget: LlmBudget,
    ) -> ReviewAttempt:
        try:
            result = await llm.complete(
                system=REVIEWER_SYSTEM_PROMPT,
                user=('{"facts":' + facts_json + ',"candidate":' + draft.model_dump_json() + "}"),
                fallback='{"passed":false,"issues":["Reviewer 暂不可用"]}',
                budget=budget,
                options=STRUCTURED_CALL_OPTIONS,
            )
        except LlmBudgetError:
            return ReviewAttempt(None, "", (), AttemptFailureKind.BUDGET)
        except LlmUnavailableError:
            return ReviewAttempt(None, "", (), AttemptFailureKind.UPSTREAM)
        if result.degraded:
            return ReviewAttempt(None, result.text, (), AttemptFailureKind.UPSTREAM)
        if not result.text:
            return ReviewAttempt(None, "", ("Reviewer 输出为空，请只输出完整 JSON",), None)
        try:
            verdict = ReviewVerdict.model_validate_json(extract_json_object(result.text))
        except ValueError:
            return ReviewAttempt(None, result.text, ("Reviewer 输出无法解析为约定 JSON",), None)
        return ReviewAttempt(verdict, result.text, tuple(verdict.issues), None)
