"""v2 商家回答反馈（契约 §8.14）：采纳与赞踩是不同语义，互不覆盖；按 §8.7.3 幂等。"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from app.core.session import SessionContext
from app.models.answer import Answer
from app.repositories.answer import AnswerRepository
from app.repositories.audit import AuditRepository
from app.repositories.v2.idempotency import IdempotencyRepository
from app.schemas.feedback import FeedbackReaction
from app.schemas.v2.memory import FeedbackKind, V2FeedbackRequest, V2FeedbackResponse
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.v2.idempotency import run_idempotent

#: 幂等域五元组里的 operation 段；改名会让既有幂等记录全部失效，谨慎变更。
OPERATION = "merchant.answers.feedback"


def _request_digest(payload: V2FeedbackRequest) -> str:
    """只取规范化后的业务输入，排除 `client_request_id` 本身（§8.7.3）。"""

    canonical = {
        "kind": payload.kind.value,
        "adopted": payload.adopted,
        "reaction": payload.reaction.value if payload.reaction else None,
        "reason": payload.reason,
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


class MerchantFeedbackService:
    def __init__(
        self,
        answers: AnswerRepository,
        idempotency: IdempotencyRepository,
        audits: AuditRepository,
    ) -> None:
        self._answers = answers
        self._idempotency = idempotency
        self._audits = audits

    async def submit(
        self,
        ctx: SessionContext,
        answer_id: str,
        payload: V2FeedbackRequest,
        *,
        secret: bytes,
        request_id: str,
    ) -> V2FeedbackResponse:
        async def fetch() -> ScopeLookupResult[Answer]:
            try:
                answer_uuid = UUID(answer_id)
            except ValueError:
                return ScopeLookupResult(resource=None, target_exists=False)
            return await self._answers.fetch_scoped(answer_uuid, ctx.merchant_id)

        answer = await require_owned(
            fetch,
            ctx=ctx,
            audits=self._audits,
            resource_type="answer",
            resource_id=answer_id,
            request_id=request_id,
        )

        async def _execute() -> dict[str, Any]:
            if payload.kind is FeedbackKind.ADOPTION:
                assert payload.adopted is not None
                feedback = await self._answers.set_adoption(
                    merchant_id=ctx.merchant_id,
                    answer_id=answer.id,
                    adopted=payload.adopted,
                )
            else:
                feedback = await self._answers.set_reaction(
                    merchant_id=ctx.merchant_id,
                    answer_id=answer.id,
                    reaction=payload.reaction.value if payload.reaction else None,
                    reason=payload.reason,
                )
            response = V2FeedbackResponse(
                answer_id=answer_id,
                adopted=feedback.is_adopted,
                reaction=FeedbackReaction(feedback.reaction) if feedback.reaction else None,
                reason=feedback.reason,
                updated_at=feedback.updated_at,
            )
            return response.model_dump(mode="json")

        body = await run_idempotent(
            repo=self._idempotency,
            ctx=ctx,
            secret=secret,
            operation=OPERATION,
            client_request_id=payload.client_request_id,
            request_digest=_request_digest(payload),
            response_status=200,
            execute=_execute,
        )
        return V2FeedbackResponse.model_validate(body)
