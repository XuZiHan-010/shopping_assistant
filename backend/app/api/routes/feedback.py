from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_database, get_db_session, get_merchant_context
from app.core.errors import error_responses
from app.core.security import MerchantContext
from app.db.session import Database
from app.repositories.answer import AnswerRepository
from app.repositories.audit import AuditRepository
from app.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.services.feedback_service import FeedbackService

router = APIRouter(tags=["feedback"])


@router.post(
    "/answers/{answer_id}/feedback",
    response_model=FeedbackResponse,
    responses=error_responses(401, 403, 404, 422),
)
async def save_feedback(
    answer_id: UUID,
    payload: FeedbackRequest,
    request: Request,
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
) -> FeedbackResponse:
    response = await FeedbackService(AnswerRepository(session), AuditRepository(database)).save(
        context, answer_id, payload, request_id=str(request.state.request_id)
    )
    await session.commit()
    return response
