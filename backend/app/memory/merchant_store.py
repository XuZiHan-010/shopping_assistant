"""商家记忆事实层及从事实确定性重建的按类别总结层。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.filters import filter_candidate, filter_persisted
from app.models.memory_v2 import MerchantMemoryFact, MerchantMemorySummary
from app.models.merchant import Merchant


class MerchantMemoryStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock_owner(self, merchant_id: UUID) -> None:
        # 同一商家的写入、删除与重建依序执行，避免派生总结与来源事实交错。
        await self._session.scalar(
            select(Merchant.id).where(Merchant.id == merchant_id).with_for_update()
        )

    async def add_fact(
        self, *, merchant_id: UUID, category: str, content: str,
        source_ref: str, at: datetime,
    ) -> MerchantMemoryFact | None:
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
        await self._lock_owner(merchant_id)
        existing = await self._session.scalar(
            select(MerchantMemoryFact).where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.source_ref == source_ref,
                MerchantMemoryFact.content == content,
                MerchantMemoryFact.deleted_at.is_(None),
            )
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

    async def facts(self, *, merchant_id: UUID) -> list[MerchantMemoryFact]:
        rows = await self._session.scalars(
            select(MerchantMemoryFact)
            .where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.deleted_at.is_(None),
            )
            .order_by(MerchantMemoryFact.created_at.desc(), MerchantMemoryFact.id.desc())
        )
        return list(rows.all())

    async def active_summaries(self, *, merchant_id: UUID) -> list[MerchantMemorySummary]:
        rows = await self._session.scalars(
            select(MerchantMemorySummary)
            .where(
                MerchantMemorySummary.merchant_id == merchant_id,
                MerchantMemorySummary.is_stale.is_(False),
            )
            .order_by(MerchantMemorySummary.category)
        )
        return list(rows.all())

    async def rebuild_summaries(
        self, *, merchant_id: UUID, at: datetime
    ) -> list[MerchantMemorySummary]:
        await self._lock_owner(merchant_id)
        facts = await self.facts(merchant_id=merchant_id)
        grouped: dict[str, list[MerchantMemoryFact]] = {}
        for fact in facts:
            grouped.setdefault(fact.category, []).append(fact)
        rows = (await self._session.scalars(
            select(MerchantMemorySummary).where(MerchantMemorySummary.merchant_id == merchant_id)
        )).all()
        by_category = {row.category: row for row in rows}
        for category, items in grouped.items():
            content = "\n".join(item.content for item in items)[:2000]
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
        return await self.active_summaries(merchant_id=merchant_id)

    async def owned_fact(
        self, *, merchant_id: UUID, fact_id: UUID
    ) -> MerchantMemoryFact | None:
        return cast(MerchantMemoryFact | None, await self._session.scalar(
            select(MerchantMemoryFact).where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.id == fact_id,
            )
        ))

    async def delete_fact(self, *, merchant_id: UUID, fact_id: UUID) -> bool:
        await self._lock_owner(merchant_id)
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
