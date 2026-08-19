"""回答质量循环的共享结果类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.schemas.answer import AnswerDraft, ReviewVerdict
from app.schemas.chat import QualityStatus


class AttemptFailureKind(StrEnum):
    UPSTREAM = "UPSTREAM"
    BUDGET = "BUDGET"


class DegradeReason(StrEnum):
    UPSTREAM = "UPSTREAM"
    VALIDATION = "VALIDATION"
    BUDGET = "BUDGET"


@dataclass(frozen=True)
class QualityOutcome:
    draft: AnswerDraft
    status: QualityStatus
    attempts: int
    notes: list[str]
    reason: DegradeReason | None


@dataclass(frozen=True)
class DraftAttempt:
    draft: AnswerDraft | None
    raw_text: str
    failure_kind: AttemptFailureKind | None


@dataclass(frozen=True)
class ReviewAttempt:
    verdict: ReviewVerdict | None
    raw_text: str
    issues: tuple[str, ...]
    failure_kind: AttemptFailureKind | None
