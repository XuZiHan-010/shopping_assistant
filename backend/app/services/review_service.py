"""独立审核候选回答；Reviewer 从不改写回答。"""

from __future__ import annotations

from typing import Final

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

# Task 5：与 quality_loop.py 同理——命名常量与
# `app.localization.catalog._REVIEW_SERVICE_MESSAGES` 的词典 key 必须保持字面
# 一致，`tests/unit/services/test_quality_loop.py` 有一条测试直接断言这一点。
_MSG_REVIEWER_UNAVAILABLE: Final = "Reviewer 暂不可用"
_MSG_REVIEWER_EMPTY_OUTPUT: Final = "Reviewer 输出为空，请只输出完整 JSON"
_MSG_REVIEWER_UNPARSEABLE: Final = "Reviewer 输出无法解析为约定 JSON"


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
                fallback=f'{{"passed":false,"issues":["{_MSG_REVIEWER_UNAVAILABLE}"]}}',
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
            return ReviewAttempt(None, "", (_MSG_REVIEWER_EMPTY_OUTPUT,), None)
        try:
            verdict = ReviewVerdict.model_validate_json(extract_json_object(result.text))
        except ValueError:
            return ReviewAttempt(None, result.text, (_MSG_REVIEWER_UNPARSEABLE,), None)
        return ReviewAttempt(verdict, result.text, tuple(verdict.issues), None)
