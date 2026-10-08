"""商家记忆事实层及从事实确定性重建的按类别总结层。

主体在构造时绑定（`MerchantMemoryOwner`），方法不接收 `merchant_id`（N4-1①）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.filters import filter_candidate, filter_persisted
from app.memory.owners import MerchantMemoryOwner
from app.models.memory_v2 import MerchantMemoryFact, MerchantMemorySummary
from app.models.merchant import Merchant

#: 单类总结的最大字符数（单条事实上限同为 2000，至少放得下一条）。
SUMMARY_MAX_CHARS = 2000


class MerchantMemoryStore:
    def __init__(self, session: AsyncSession, owner: MerchantMemoryOwner) -> None:
        if not isinstance(owner, MerchantMemoryOwner):
            raise TypeError("MerchantMemoryStore 需要 MerchantMemoryOwner")
        self._session = session
        self._owner = owner

    async def _lock_owner(self) -> None:
        # 同一商家的写入、删除与重建依序执行，避免派生总结与来源事实交错。
        await self._session.scalar(
            select(Merchant.id).where(Merchant.id == self._owner.merchant_id).with_for_update()
        )

    async def add_fact(
        self, *, category: str, content: str, source_ref: str, at: datetime,
    ) -> MerchantMemoryFact | None:
        merchant_id = self._owner.merchant_id
        fact = SimpleNamespace(category=category, content=content)
        try:
            conversation_id, message_id = source_ref.split(":")
            UUID(conversation_id)
            UUID(message_id)
        except (ValueError, AttributeError):
            return None
        if (
            not category or len(category) > 64 or not content or len(content) > 2000
            or filter_candidate(fact).rejected
        ):
            return None
        if filter_persisted(fact).rejected:
            return None
        await self._lock_owner()
        # 同类同内容即同一偏好：换一个回合再说一遍不再堆一条（台账 M5），来源保留首次出处。
        existing = await self._session.scalar(
            select(MerchantMemoryFact)
            .where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.category == category,
                MerchantMemoryFact.content == content,
                MerchantMemoryFact.deleted_at.is_(None),
            )
            .limit(1)
        )
        if existing is not None:
            return existing
        row = MerchantMemoryFact(
            merchant_id=merchant_id, category=category, content=content,
            source_ref=source_ref, created_at=at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def facts(self) -> list[MerchantMemoryFact]:
        merchant_id = self._owner.merchant_id
        rows = await self._session.scalars(
            select(MerchantMemoryFact)
            .where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.deleted_at.is_(None),
            )
            .order_by(MerchantMemoryFact.created_at.desc(), MerchantMemoryFact.id.desc())
        )
        return list(rows.all())

    async def active_summaries(self) -> list[MerchantMemorySummary]:
        merchant_id = self._owner.merchant_id
        rows = await self._session.scalars(
            select(MerchantMemorySummary)
            .where(
                MerchantMemorySummary.merchant_id == merchant_id,
                MerchantMemorySummary.is_stale.is_(False),
            )
            .order_by(MerchantMemorySummary.category)
        )
        return list(rows.all())

    async def rebuild_summaries(self, *, at: datetime) -> list[MerchantMemorySummary]:
        merchant_id = self._owner.merchant_id
        await self._lock_owner()
        facts = await self.facts()
        grouped: dict[str, list[MerchantMemoryFact]] = {}
        for fact in facts:
            grouped.setdefault(fact.category, []).append(fact)
        rows = (await self._session.scalars(
            select(MerchantMemorySummary).where(MerchantMemorySummary.merchant_id == merchant_id)
        )).all()
        by_category = {row.category: row for row in rows}
        for category, grouped_items in grouped.items():
            # 按新到旧逐条放入，放不下的事实整条不进总结，也不进 source_fact_ids（台账 M6）：
            # 截断半条会让总结与来源列表对不上，删除来源时依赖关系也会判错。
            items: list[MerchantMemoryFact] = []
            length = 0
            for item in grouped_items:
                added = len(item.content) + (1 if items else 0)
                if length + added > SUMMARY_MAX_CHARS:
                    break
                items.append(item)
                length += added
            if not items:
                continue
            content = "\n".join(item.content for item in items)
            if filter_persisted(SimpleNamespace(category=category, content=content)).rejected:
                # 合并后重新拼出敏感信息：本类不生成总结，旧总结随 obsolete 一并删除（N4-1②）。
                continue
            summary = by_category.pop(category, None)
            if summary is None:
                summary = MerchantMemorySummary(merchant_id=merchant_id, category=category)
                self._session.add(summary)
            summary.content = content
            summary.source_fact_ids = [str(item.id) for item in items]
            summary.rebuilt_at = at
            summary.is_stale = False
        for obsolete in by_category.values():
            await self._session.delete(obsolete)
        await self._session.flush()
        return await self.active_summaries()

    async def owned_fact(self, *, fact_id: UUID) -> MerchantMemoryFact | None:
        merchant_id = self._owner.merchant_id
        return cast(MerchantMemoryFact | None, await self._session.scalar(
            select(MerchantMemoryFact).where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.id == fact_id,
            )
        ))

    async def delete_fact(self, *, fact_id: UUID) -> bool:
        merchant_id = self._owner.merchant_id
        await self._lock_owner()
        deleted = await self._session.execute(
            update(MerchantMemoryFact)
            .where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.id == fact_id,
                MerchantMemoryFact.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC))
            .returning(MerchantMemoryFact.id)
        )
        if deleted.scalar_one_or_none() is None:
            return False
        await self._session.execute(
            update(MerchantMemorySummary)
            .where(
                MerchantMemorySummary.merchant_id == merchant_id,
                MerchantMemorySummary.source_fact_ids.contains([str(fact_id)]),
            )
            .values(is_stale=True)
        )
        await self._session.flush()
        return True
