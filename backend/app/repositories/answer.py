from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer import Answer, Feedback
from app.models.conversation import Message


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

    async def recent_answers_for_category(
        self,
        *,
        merchant_id: UUID,
        category: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """取该商家该分类最近若干轮成功问答，供记忆沉淀压缩。

        分类过滤放在 SQL 里而不是取回后在 Python 过滤：参考实现
        ``recentAnswers(merchantId, 80)`` 之后再 ``belongsToCategory`` 是因为它的
        JDBC 查询没有分类条件，我们的 ``response_payload`` 是 JSONB，可以直接下推，
        既少搬运用不上的行，也保证真的拿满该分类的 80 轮。

        商家范围由 ``merchant_id`` 强制过滤（R5）；分类不匹配、未成功的回答一律排除，
        避免把失败轮次或其他业务域的内容混进记忆。
        """

        statement = (
            select(Answer.created_at, Answer.response_payload, Message.content)
            .join(Message, Message.id == Answer.user_message_id)
            .where(
                Answer.merchant_id == merchant_id,
                Message.merchant_id == merchant_id,
                Answer.processing_status == "SUCCEEDED",
                Answer.response_payload["category"].astext == category,
            )
            .order_by(Answer.created_at.desc(), Answer.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            {
                "question": question,
                "answer": (payload or {}).get("answer"),
                "category": category,
                "created_at": created_at.isoformat(),
            }
            for created_at, payload, question in rows
        ]

    async def top_category_questions(
        self,
        *,
        merchant_id: UUID,
        category: str,
        limit: int,
    ) -> list[str]:
        """取商家指定分类的历史高频问题，供「猜你想问」使用。

        问题按出现次数降序，相同频次再按最近回答时间降序。Answer 与关联的
        用户 Message 均强制使用商家范围，且仅统计有分类标记的成功回答。
        """

        occurrences = func.count().label("occurrences")
        latest = func.max(Answer.created_at).label("latest")
        statement = (
            select(Message.content)
            .join(Answer, Answer.user_message_id == Message.id)
            .where(
                Answer.merchant_id == merchant_id,
                Message.merchant_id == merchant_id,
                Answer.processing_status == "SUCCEEDED",
                Answer.response_payload["category"].astext == category,
                Message.content != "",
            )
            .group_by(Message.content)
            .order_by(occurrences.desc(), latest.desc())
            .limit(limit)
        )
        # 推荐问题是主回答之外的可选能力。SQL 错误必须仅回滚这里的 savepoint，
        # 不能让共享的 ChatService 会话进入 PostgreSQL 的 aborted 状态。
        async with self._session.begin_nested():
            rows = (await self._session.execute(statement)).all()
        return [question for (question,) in rows]
