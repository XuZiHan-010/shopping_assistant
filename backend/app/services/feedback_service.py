from __future__ import annotations

from uuid import UUID

from app.core.errors import MerchantScopeViolationError, ResourceNotFoundError
from app.core.security import MerchantContext
from app.repositories.answer import AnswerRepository
from app.repositories.audit import AuditRepository
from app.schemas.feedback import FeedbackRequest, FeedbackResponse


class FeedbackService:
    def __init__(self, answers: AnswerRepository, audit: AuditRepository) -> None:
        self._answers = answers
        self._audit = audit

    async def save(
        self,
        context: MerchantContext,
        answer_id: UUID,
        payload: FeedbackRequest,
        *,
        request_id: str,
    ) -> FeedbackResponse:
        if await self._answers.get_for_merchant(answer_id, context.merchant_id) is None:
            if await self._answers.exists(answer_id):
                await self._audit.record_scope_violation(
                    actor_merchant_id=context.merchant_id,
                    resource_type="answer",
                    resource_id=str(answer_id),
                    request_id=request_id,
                )
                raise MerchantScopeViolationError
            raise ResourceNotFoundError("回答")
        feedback = await self._answers.upsert_feedback(
            merchant_id=context.merchant_id,
            answer_id=answer_id,
            is_adopted=payload.is_adopted,
            reaction=payload.reaction.value if payload.reaction else None,
        )
        return FeedbackResponse(
            answer_id=answer_id,
            is_adopted=feedback.is_adopted,
            reaction=feedback.reaction,
        )
