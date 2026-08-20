"""商家记忆仓储。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import MerchantMemory


class MerchantMemoryRepository:
    """商家记忆读写，所有查询均强制按商家范围过滤。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_merchant(self, merchant_id: UUID, category: str) -> list[MerchantMemory]:
        statement = select(MerchantMemory).where(
            MerchantMemory.merchant_id == merchant_id,
            MerchantMemory.category == category,
            MerchantMemory.status == "ACTIVE",
        )
        result = await self._session.execute(statement)
        return list(result.scalars())

    async def upsert(
        self,
        *,
        merchant_id: UUID,
        category: str,
        content: str,
    ) -> MerchantMemory:
        """按商家与分类全量覆盖，对应参考实现的 ``Files.writeString``。

        用 ``ON CONFLICT DO UPDATE`` 而非「先 SELECT 再决定插入或更新」，是因为
        本方法会被后台沉淀任务并发调用（同一商家短时间内多轮同分类提问）：
        先查后写在两次并发调用都读到「不存在」时会撞上
        ``uq_merchant_memories_merchant_category`` 唯一约束抛 IntegrityError，
        与 ``app.repositories.answer.AnswerRepository.upsert_feedback`` 同一场景同一写法。
        """

        statement = (
            insert(MerchantMemory)
            .values(
                merchant_id=merchant_id,
                category=category,
                content=content,
                status="ACTIVE",
            )
            .on_conflict_do_update(
                constraint="uq_merchant_memories_merchant_category",
                set_={
                    "content": content,
                    "status": "ACTIVE",
                    "version": MerchantMemory.version + 1,
                },
            )
            .returning(MerchantMemory)
        )
        # PostgreSQL 的 DML RETURNING 会复用 Session identity map 内的实例；同一 Session
        # 连续写入时，调用级 populate_existing 不会刷新该实例。显式 refresh 才能保证返回
        # 本次覆盖后的 content 和 version。
        memory = (await self._session.execute(statement)).scalar_one()
        await self._session.refresh(memory)
        return memory
