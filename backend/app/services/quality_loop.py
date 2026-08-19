"""生成、校验和独立复核的有限质量循环。"""

from __future__ import annotations

from typing import Final

from app.llm.client import (
    LlmBudget,
    LlmBudgetExceededError,
    LlmClient,
    LlmDailyBudgetExceededError,
    LlmUnavailableError,
)
from app.schemas.answer import AnswerDraft
from app.schemas.chat import QualityStatus
from app.services.answer_service import AnswerFacts, AnswerService
from app.services.quality_types import (
    AttemptFailureKind,
    DegradeReason,
    QualityOutcome,
    ReviewAttempt,
)
from app.services.review_service import ReviewService


class QualityLoop:
    def __init__(
        self,
        *,
        max_attempts: int,
        answer_service: AnswerService | None = None,
        review_service: ReviewService | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts 必须至少为 1")
        self._max_attempts = max_attempts
        self._answers = answer_service or AnswerService()
        self._reviews = review_service or ReviewService()

    async def run(
        self,
        facts: AnswerFacts,
        answer_llm: LlmClient,
        reviewer_llm: LlmClient | None,
        budget: LlmBudget,
    ) -> QualityOutcome:
        fallback = self._answers.fallback_draft(facts)
        notes: list[str] = []
        issues: list[str] = []
        previous = ""
        for attempt in range(1, self._max_attempts + 1):
            try:
                drafted = await self._answers.compose_once(
                    facts, answer_llm, budget, previous=previous, issues=issues
                )
            except LlmDailyBudgetExceededError:
                # 日预算与单请求预算都是 BUDGET，但对用户是两件事：前者今天不用再试，
                # 后者换个更简单的问题就能答。措辞必须分开，否则排查方向会被带偏。
                return _fallback(
                    fallback,
                    attempt - 1,
                    notes,
                    DegradeReason.BUDGET,
                    note="今日模型用量已达上限，本次只提供受控数据摘要",
                )
            except LlmBudgetExceededError:
                return _fallback(fallback, attempt - 1, notes, DegradeReason.BUDGET)
            except LlmUnavailableError:
                return _fallback(fallback, attempt - 1, notes, DegradeReason.UPSTREAM)

            if drafted.failure_kind is AttemptFailureKind.BUDGET:
                return _fallback(fallback, attempt, notes, DegradeReason.BUDGET)
            if drafted.failure_kind is AttemptFailureKind.UPSTREAM:
                return _fallback(fallback, attempt, notes, DegradeReason.UPSTREAM)

            previous = drafted.raw_text
            reviewed = ReviewAttempt(None, "", (), None)
            if drafted.draft is None:
                issues = [
                    "模型返回空正文，请重新只输出完整 JSON"
                    if not drafted.raw_text
                    else "上一版输出无法解析为约定的 JSON 对象，请只输出完整 JSON"
                ]
            else:
                issues = self._answers.validate_issues(drafted.draft, facts)
                if not issues:
                    if reviewer_llm is None:
                        notes.append("未执行独立复核，本次只提供受控数据摘要")
                        return _fallback(fallback, attempt, notes, DegradeReason.UPSTREAM)
                    reviewed = await self._reviews.review_once(
                        drafted.draft, self._answers.facts_json(facts), reviewer_llm, budget
                    )
                    if reviewed.failure_kind is AttemptFailureKind.BUDGET:
                        return _fallback(fallback, attempt, notes, DegradeReason.BUDGET)
                    if reviewed.failure_kind is AttemptFailureKind.UPSTREAM:
                        return _fallback(fallback, attempt, notes, DegradeReason.UPSTREAM)
                    issues = list(reviewed.issues)

            if (
                drafted.draft is not None
                and reviewed.verdict is not None
                and reviewed.verdict.passed
                and not issues
            ):
                notes.extend(reviewed.verdict.advisory_notes)
                notes.append(f"第 {attempt} 轮通过本地校验和独立复核前后比对")
                return QualityOutcome(drafted.draft, QualityStatus.PASSED, attempt, notes, None)
            notes.append(f"第 {attempt} 轮回答被打回：{'；'.join(issues)}")

        notes.append("达到最大重试次数，使用确定性降级结果")
        return _fallback(fallback, self._max_attempts, notes, DegradeReason.VALIDATION)


_DEGRADE_NOTES: Final[dict[DegradeReason, str]] = {
    DegradeReason.UPSTREAM: "模型或独立复核暂不可用，本次只提供受控数据摘要",
    DegradeReason.BUDGET: "本次请求的模型预算已达上限，本次只提供受控数据摘要",
    DegradeReason.VALIDATION: "回答未通过校验，本次只提供受控数据摘要",
}


def _fallback(
    draft: AnswerDraft,
    attempts: int,
    notes: list[str],
    reason: DegradeReason,
    *,
    note: str | None = None,
) -> QualityOutcome:
    message = note or _DEGRADE_NOTES[reason]
    if not notes or notes[-1] != message:
        notes.append(message)
    return QualityOutcome(draft, QualityStatus.DEGRADED, attempts, notes, reason)
