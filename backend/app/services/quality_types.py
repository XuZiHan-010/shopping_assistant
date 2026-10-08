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
    # 以下三项只由 v2 工具循环产生（§6.10）；v1 不会产生它们，v1 的映射表不需要登记。
    LIMIT = "LIMIT"  # 轮数或工具调用次数触顶
    TIMEOUT = "TIMEOUT"  # 墙钟时间触顶
    CANCELLED = "CANCELLED"  # 客户端断开


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
