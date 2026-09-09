"""商家记忆仓储。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.localization.locales import detect_source_language, hash_source_text
from app.models.knowledge import MerchantMemory
from app.repositories.localization import LocalizationRepository, LocalizationScope


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

    async def list_all_for_merchant(self, merchant_id: UUID) -> list[MerchantMemory]:
        """闸门打分专用（`KnowledgeRetrieval.score_question`）：拿该商家全部分类的
        记忆，而不是 `list_for_merchant` 要求的某一个已知分类——闸门运行时业务
        分类尚未确定。
        """

        statement = select(MerchantMemory).where(
            MerchantMemory.merchant_id == merchant_id,
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

        Task 8：``merchant_memories.source_locale`` 是 NOT NULL 且无 DB 默认值
        的列（Task 3），本方法是它唯一的写入路径，因此在这里按写入的
        ``content`` 用 ``detect_source_language()`` 分类（不同请求可能用不同
        显示语言压缩记忆——见 ``MemoryService.consolidate()`` 的 ``locale``
        参数——``source_locale`` 必须跟着这次真正写入的文本走，不能固定假设
        为 zh-CN）。压缩/替换同一 ``(merchant_id, category)`` 的记忆是本表
        唯一的"删除旧内容"场景（没有独立的 delete/archive 入口）：写入前先
        取旧正文的哈希，写入后清理该哈希对应的机器缓存与（理论上不会存在,
        但仍按 Step 4 要求防御性清理的）资源级人工译文，避免旧内容的派生
        缓存无限期滞留。
        """

        existing = (
            await self._session.execute(
                select(MerchantMemory.id, MerchantMemory.content).where(
                    MerchantMemory.merchant_id == merchant_id,
                    MerchantMemory.category == category,
                )
            )
        ).first()

        statement = (
            insert(MerchantMemory)
            .values(
                merchant_id=merchant_id,
                category=category,
                content=content,
                status="ACTIVE",
                source_locale=str(detect_source_language(content)),
            )
            .on_conflict_do_update(
                constraint="uq_merchant_memories_merchant_category",
                set_={
                    "content": content,
                    "status": "ACTIVE",
                    "version": MerchantMemory.version + 1,
                    "source_locale": str(detect_source_language(content)),
                },
            )
            .returning(MerchantMemory)
        )
        # PostgreSQL 的 DML RETURNING 会复用 Session identity map 内的实例；同一 Session
        # 连续写入时，调用级 populate_existing 不会刷新该实例。显式 refresh 才能保证返回
        # 本次覆盖后的 content 和 version。
        memory = (await self._session.execute(statement)).scalar_one()
        await self._session.refresh(memory)

        if existing is not None and existing.content != content:
            localization = LocalizationRepository(self._session)
            await localization.delete_machine_by_hashes(
                scope=LocalizationScope(kind="MERCHANT", merchant_id=merchant_id),
                source_hashes=[hash_source_text(existing.content)],
            )
            await localization.delete_resource_localizations(
                resource_type="MERCHANT_MEMORY", resource_id=existing.id
            )
        return memory
