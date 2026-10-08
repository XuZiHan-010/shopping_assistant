"""商家回答反馈（PRD M13，契约 §8.14.4）：`POST /api/v2/merchant/answers/{answer_id}/feedback`。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret
from app.api.session_deps import get_session_audit_repository, require_merchant_session
from app.core.errors import error_responses
from app.core.session import SessionContext
from app.repositories.answer import AnswerRepository
from app.repositories.audit import AuditRepository
from app.repositories.v2.idempotency import IdempotencyRepository
from app.schemas.v2.memory import V2FeedbackRequest, V2FeedbackResponse
from app.services.v2.feedback import MerchantFeedbackService

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-feedback"])


@router.post(
    "/answers/{answer_id}/feedback",
    response_model=V2FeedbackResponse,
    status_code=200,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def submit_answer_feedback(
    answer_id: str,
    payload: V2FeedbackRequest,
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> V2FeedbackResponse:
    service = MerchantFeedbackService(
        AnswerRepository(session), IdempotencyRepository(session), audits
    )
    response = await service.submit(
        ctx,
        answer_id,
        payload,
        secret=secret,
        request_id=str(request.state.request_id),
    )
    await session.commit()
    return response
