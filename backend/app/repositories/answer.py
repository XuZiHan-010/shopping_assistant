from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer import Answer, Feedback


class AnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_merchant(self, answer_id: UUID, merchant_id: UUID) -> Answer | None:
        return cast(
            Answer | None,
            await self._session.scalar(
                select(Answer).where(Answer.id == answer_id, Answer.merchant_id == merchant_id)
            ),
        )

    async def exists(self, answer_id: UUID) -> bool:
        return (
            await self._session.scalar(select(Answer.id).where(Answer.id == answer_id)) is not None
        )

    async def upsert_feedback(
        self, *, merchant_id: UUID, answer_id: UUID, is_adopted: bool, reaction: str | None
    ) -> Feedback:
        statement = (
            insert(Feedback)
            .values(
                merchant_id=merchant_id,
                answer_id=answer_id,
                is_adopted=is_adopted,
                reaction=reaction,
            )
            .on_conflict_do_update(
                constraint="uq_feedback_merchant_answer",
                set_={"is_adopted": is_adopted, "reaction": reaction},
            )
            .returning(Feedback)
        )
        return (await self._session.execute(statement)).scalar_one()
