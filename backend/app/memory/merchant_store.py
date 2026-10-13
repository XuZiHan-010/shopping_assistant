"""商家记忆事实层及从事实确定性重建的按类别总结层。

主体在构造时绑定（`MerchantMemoryOwner`），方法不接收 `merchant_id`（N4-1①）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
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

    async def _lock_owner(self) -> Merchant:
        # 同一商家的写入、删除与重建依序执行，避免派生总结与来源事实交错。
        row = await self._session.scalar(
            select(Merchant)
            .where(Merchant.id == self._owner.merchant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ValueError("记忆主体不存在")
        return row

    async def generation(self) -> int:
        return (await self._lock_owner()).memory_generation

    async def add_fact(
        self,
        *,
        category: str,
        content: str,
        source_ref: str,
        at: datetime,
        key: str | None = None,
        source_order: int = 0,
        expected_generation: int | None = None,
    ) -> MerchantMemoryFact | None:
        merchant_id = self._owner.merchant_id
        fact = SimpleNamespace(category=category, content=content, key=key)
        try:
            conversation_id, message_id = source_ref.split(":")
            UUID(conversation_id)
            UUID(message_id)
        except (ValueError, AttributeError):
            return None
        if (
            not category
            or len(category) > 64
            or not content
            or len(content) > 2000
            or (key is not None and (not key or len(key) > 100))
            or filter_candidate(fact).rejected
        ):
            return None
        if filter_persisted(fact).rejected:
            return None
        owner = await self._lock_owner()
        if expected_generation is not None and owner.memory_generation != expected_generation:
            return None
        if key is not None:
            existing_key = await self._session.scalar(
                select(MerchantMemoryFact)
                .where(
                    MerchantMemoryFact.merchant_id == merchant_id,
                    MerchantMemoryFact.category == category,
                    MerchantMemoryFact.key == key,
                    MerchantMemoryFact.deleted_at.is_(None),
                )
                .limit(1)
            )
            if existing_key is not None:
                if (at, source_order) <= (existing_key.created_at, existing_key.source_order):
                    return None
                await self._session.execute(
                    update(MerchantMemorySummary)
                    .where(
                        MerchantMemorySummary.merchant_id == merchant_id,
                        MerchantMemorySummary.source_fact_ids.contains([str(existing_key.id)]),
                    )
                    .values(is_stale=True)
                )
                existing_key.content = content
                existing_key.source_ref = source_ref
                existing_key.created_at = at
                existing_key.source_order = source_order
                await self._session.flush()
                return existing_key
        # 同类同内容即同一偏好：换一个回合再说一遍不再堆一条（台账 M5），来源保留首次出处。
        existing = await self._session.scalar(
            select(MerchantMemoryFact)
            .where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.category == category,
                MerchantMemoryFact.content == content,
                MerchantMemoryFact.key == key,
                MerchantMemoryFact.deleted_at.is_(None),
            )
            .limit(1)
        )
        if existing is not None:
            return existing
        row = MerchantMemoryFact(
            merchant_id=merchant_id,
            category=category,
            content=content,
            source_ref=source_ref,
            created_at=at,
            key=key,
            source_order=source_order,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def facts(
        self,
        *,
        category: str | None = None,
        limit: int | None = None,
        exclude_ids: tuple[str, ...] = (),
    ) -> list[MerchantMemoryFact]:
        merchant_id = self._owner.merchant_id
        statement = (
            select(MerchantMemoryFact)
            .where(
                MerchantMemoryFact.merchant_id == merchant_id,
                MerchantMemoryFact.deleted_at.is_(None),
            )
            .order_by(MerchantMemoryFact.created_at.desc(), MerchantMemoryFact.id.desc())
        )
        if category is not None:
            statement = statement.where(MerchantMemoryFact.category == category)
        if exclude_ids:
            statement = statement.where(
                MerchantMemoryFact.id.not_in([UUID(i) for i in exclude_ids])
            )
        if limit is not None:
            statement = statement.limit(limit)
        rows = await self._session.scalars(statement)
        return list(rows.all())

    async def directory(self) -> list[dict[str, object]]:
        rows = await self._session.execute(
            select(MerchantMemoryFact.category, func.max(MerchantMemoryFact.created_at).label("at"))
            .where(
                MerchantMemoryFact.merchant_id == self._owner.merchant_id,
                MerchantMemoryFact.deleted_at.is_(None),
            )
            .group_by(MerchantMemoryFact.category)
            .order_by(func.max(MerchantMemoryFact.created_at).desc(), MerchantMemoryFact.category)
            .limit(21)
        )
        return [
            {"category": category, "last_confirmed_at": confirmed.isoformat()}
            for category, confirmed in rows
        ]

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
        rows = (
            await self._session.scalars(
                select(MerchantMemorySummary).where(
                    MerchantMemorySummary.merchant_id == merchant_id
                )
            )
        ).all()
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
        return cast(
            MerchantMemoryFact | None,
            await self._session.scalar(
                select(MerchantMemoryFact).where(
                    MerchantMemoryFact.merchant_id == merchant_id,
                    MerchantMemoryFact.id == fact_id,
                )
            ),
        )

    async def delete_fact(self, *, fact_id: UUID) -> bool:
        merchant_id = self._owner.merchant_id
        owner = await self._lock_owner()
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
        owner.memory_generation += 1
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
