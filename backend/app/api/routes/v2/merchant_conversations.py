"""商家会话目录（PRD §12.4，契约 §8.9.2）：列表、详情与删除。

只看得到本店由商家 Chat 创建、未删除的对话；同店顾客的对话不在其中（两端按登录主体隔离）。
不存在、别家的、顾客的与已删除的对话对外同一种 `403 RESOURCE_FORBIDDEN`。
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import get_session_audit_repository, require_merchant_session
from app.api.v2_deps import get_cursor_codec
from app.core.errors import error_responses
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.answer import Feedback
from app.models.conversation import Conversation, Message
from app.repositories.answer import AnswerRepository
from app.repositories.audit import AuditRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.merchant_session import (
    MerchantChatResponse,
    MerchantConversationDetailResponse,
    MerchantConversationFeedbackState,
    MerchantConversationMessage,
    MerchantConversationSummary,
)
from app.services.v2.conversations import ConversationDirectory
from app.services.v2.cursor import CursorCodec

router = APIRouter(prefix="/v2/merchant/conversations", tags=["v2-merchant-conversations"])

ConversationIdPath = Annotated[str, Path(min_length=1, max_length=128)]
CursorQuery = Annotated[str | None, Query(min_length=1, max_length=2048)]
LimitQuery = Annotated[int, Query(ge=1, le=100)]


def _directory(
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
) -> ConversationDirectory:
    return ConversationDirectory(
        session,
        ctx=ctx,
        surface="MERCHANT",
        principal_secret=principal_secret,
        audits=audits,
        codec=codec,
        request_id=str(getattr(request.state, "request_id", "unknown")),
    )


Directory = Annotated[ConversationDirectory, Depends(_directory)]
Locale = Annotated[SupportedLocale, Depends(get_request_locale)]


def _summary(row: Conversation) -> MerchantConversationSummary:
    return MerchantConversationSummary(
        id=str(row.id), title=row.title or "", created_at=row.created_at, updated_at=row.updated_at
    )


def _message(row: Message, feedback: dict[UUID, Feedback]) -> MerchantConversationMessage:
    assistant = row.role == "ASSISTANT"
    answer = MerchantChatResponse.model_validate(row.response_payload) if assistant else None
    saved = feedback.get(UUID(answer.id)) if answer else None
    return MerchantConversationMessage(
        id=str(row.id),
        role="assistant" if assistant else "user",
        content=row.content,
        created_at=row.created_at,
        answer=answer,
        feedback=(
            MerchantConversationFeedbackState(
                adopted=saved.is_adopted if saved else False,
                reaction=saved.reaction if saved else None,
                reason=saved.reason if saved else None,
            )
            if assistant
            else None
        ),
    )


@router.get(
    "",
    response_model=CursorPage[MerchantConversationSummary],
    responses=error_responses(401, 403, 422, 503),
)
async def list_merchant_conversations(
    directory: Directory,
    locale: Locale,
    cursor: CursorQuery = None,
    limit: LimitQuery = 20,
) -> CursorPage[MerchantConversationSummary]:
    """仅当前商家对话；`updated_at DESC, id DESC`（最近活动在前）。"""

    page = await directory.list_page(cursor=cursor, limit=limit, locale=locale)
    return CursorPage[MerchantConversationSummary](
        items=[_summary(row) for row in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/{conversation_id}",
    response_model=MerchantConversationDetailResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def get_merchant_conversation(
    conversation_id: ConversationIdPath,
    directory: Directory,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    locale: Locale,
    cursor: CursorQuery = None,
    limit: LimitQuery = 20,
) -> MerchantConversationDetailResponse:
    """消息 `created_at ASC, id ASC`；游标另绑定 conversation_id。"""

    conversation = await directory.require(conversation_id)
    page = await directory.messages_page(conversation, cursor=cursor, limit=limit, locale=locale)
    answer_ids = {
        UUID(row.response_payload["id"])
        for row in page.items
        if row.role == "ASSISTANT" and row.response_payload is not None
    }
    feedback = await AnswerRepository(session).feedback_for_merchant_answers(
        merchant_id=ctx.merchant_id,
        conversation_id=conversation.id,
        answer_ids=answer_ids,
    )
    return MerchantConversationDetailResponse(
        conversation=_summary(conversation),
        messages=CursorPage[MerchantConversationMessage](
            items=[_message(row, feedback) for row in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        ),
    )


@router.delete(
    "/{conversation_id}",
    status_code=204,
    response_class=Response,
    responses=error_responses(401, 403, 422, 503),
)
async def delete_merchant_conversation(
    conversation_id: ConversationIdPath,
    directory: Directory,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """软删除并同事务清掉来源状态；删除后再次请求统一 403。"""

    conversation = await directory.require(conversation_id)
    await directory.delete(conversation)
    await session.commit()
    return Response(status_code=204)
