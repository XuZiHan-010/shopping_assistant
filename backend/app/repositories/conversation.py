"""会话数据访问，所有业务方法显式要求 merchant_id。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer import Answer, Feedback
from app.models.conversation import Conversation, Message


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, merchant_id: UUID, title: str | None = None) -> Conversation:
        conversation = Conversation(merchant_id=merchant_id, title=title)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get_or_create_daily_report_conversation(self, merchant_id: UUID) -> Conversation:
        """返回每商家唯一的日报系统会话，不按标题识别系统资源。"""

        existing = await self._session.scalar(
            select(Conversation).where(
                Conversation.merchant_id == merchant_id,
                Conversation.conversation_kind == "DAILY_REPORT",
            )
        )
        if existing is not None:
            return existing

        try:
            # 并发首建时，条件唯一索引才是最终裁决；savepoint 让输家可以继续在
            # 同一请求事务中重读赢家行，而不是把整个 AsyncSession 标记为失败。
            async with self._session.begin_nested():
                created = Conversation(
                    merchant_id=merchant_id,
                    title="每日经营报告",
                    conversation_kind="DAILY_REPORT",
                )
                self._session.add(created)
                await self._session.flush()
        except IntegrityError:
            raced = await self._session.scalar(
                select(Conversation).where(
                    Conversation.merchant_id == merchant_id,
                    Conversation.conversation_kind == "DAILY_REPORT",
                )
            )
            if raced is not None:
                return raced
            raise
        return created

    async def list_for_merchant(
        self,
        merchant_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[Conversation]:
        result = await self._session.scalars(
            select(Conversation)
            .where(
                Conversation.merchant_id == merchant_id,
                Conversation.conversation_kind == "CHAT",
            )
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def get_for_merchant(
        self,
        conversation_id: UUID,
        merchant_id: UUID,
    ) -> Conversation | None:
        result = await self._session.scalars(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.merchant_id == merchant_id,
            )
        )
        return result.one_or_none()

    async def exists(self, conversation_id: UUID) -> bool:
        return bool(
            await self._session.scalar(select(exists().where(Conversation.id == conversation_id)))
        )

    async def delete_for_merchant(
        self,
        conversation_id: UUID,
        merchant_id: UUID,
    ) -> bool:
        conversation = await self.get_for_merchant(conversation_id, merchant_id)
        if conversation is None:
            return False
        await self._session.delete(conversation)
        await self._session.flush()
        return True

    async def create_message(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
    ) -> Message:
        message = Message(
            merchant_id=merchant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def touch_conversation(self, merchant_id: UUID, conversation_id: UUID) -> None:
        """推进会话的 updated_at。

        新增消息只写 messages 表，不会触发 conversations 行的 onupdate，
        而 updated_at 是 ConversationSummary 的对外字段，不能长期等于 created_at。
        """

        await self._session.execute(
            update(Conversation)
            .where(
                Conversation.merchant_id == merchant_id,
                Conversation.id == conversation_id,
            )
            .values(updated_at=func.now())
        )

    async def list_messages_for_conversation(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
    ) -> list[Message]:
        result = await self._session.scalars(
            select(Message)
            .where(
                Message.merchant_id == merchant_id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(result)

    async def list_succeeded_answers_for_conversation(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
    ) -> list[tuple[Answer, Feedback | None]]:
        result = await self._session.execute(
            select(Answer, Feedback)
            .outerjoin(
                Feedback,
                and_(
                    Feedback.answer_id == Answer.id,
                    Feedback.merchant_id == merchant_id,
                ),
            )
            .where(
                Answer.merchant_id == merchant_id,
                Answer.conversation_id == conversation_id,
                Answer.processing_status == "SUCCEEDED",
            )
            .order_by(Answer.created_at.asc(), Answer.id.asc())
        )
        return list(result.tuples())

    async def get_answer_by_client_request(
        self,
        merchant_id: UUID,
        client_request_id: str,
    ) -> Answer | None:
        result = await self._session.scalar(
            select(Answer).where(
                Answer.merchant_id == merchant_id,
                Answer.client_request_id == client_request_id,
            )
        )
        return result

    async def create_processing_answer(
        self,
        merchant_id: UUID,
        conversation_id: UUID,
        user_message_id: UUID | None,
        client_request_id: str,
        request_digest: str,
    ) -> Answer:
        answer = Answer(
            merchant_id=merchant_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            client_request_id=client_request_id,
            request_digest=request_digest,
            processing_status="PROCESSING",
        )
        self._session.add(answer)
        await self._session.flush()
        return answer

    async def mark_answer_succeeded(
        self,
        answer: Answer,
        response_payload: dict[str, Any],
    ) -> None:
        answer.processing_status = "SUCCEEDED"
        answer.response_payload = response_payload
        answer.error_payload = None
        await self._session.flush()

    async def mark_answer_failed(
        self,
        answer: Answer,
        *,
        retryable: bool,
        error_payload: dict[str, Any],
    ) -> None:
        answer.processing_status = "FAILED_RETRYABLE" if retryable else "FAILED_FINAL"
        answer.error_payload = error_payload
        answer.response_payload = None
        await self._session.flush()

    async def reset_answer_processing(self, answer: Answer) -> None:
        answer.processing_status = "PROCESSING"
        answer.error_payload = None
        await self._session.flush()
