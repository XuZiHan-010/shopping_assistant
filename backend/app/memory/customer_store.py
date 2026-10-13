"""按店铺与已绑定顾客隔离的事实记忆和偏好开关。

主体在构造时绑定（`CustomerMemoryOwner`），方法不接收 `merchant_id` / `buyer_key`：调用方无从
传入别人的主体，所有查询都由本类按绑定主体过滤（N4-1①）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.filters import filter_candidate, filter_persisted
from app.memory.owners import CustomerMemoryOwner
from app.models.memory_v2 import CustomerMemory, CustomerMemoryPreference

RETENTION = timedelta(days=180)


class CustomerMemoryStore:
    def __init__(self, session: AsyncSession, owner: CustomerMemoryOwner) -> None:
        if not isinstance(owner, CustomerMemoryOwner):
            raise TypeError("CustomerMemoryStore 需要 CustomerMemoryOwner")
        self._session = session
        self._owner = owner

    async def _locked_preference(self) -> CustomerMemoryPreference:
        merchant_id, buyer_key = self._owner.merchant_id, self._owner.buyer_key
        await self._session.execute(
            pg_insert(CustomerMemoryPreference)
            .values(merchant_id=merchant_id, buyer_key=buyer_key, memory_enabled=True)
            .on_conflict_do_nothing(index_elements=["merchant_id", "buyer_key"])
        )
        row = await self._session.scalar(
            select(CustomerMemoryPreference)
            .where(
                CustomerMemoryPreference.merchant_id == merchant_id,
                CustomerMemoryPreference.buyer_key == buyer_key,
            )
            .with_for_update()
        )
        assert row is not None
        return row

    async def memory_enabled(self) -> bool:
        result = await self._session.scalar(
            select(CustomerMemoryPreference.memory_enabled).where(
                CustomerMemoryPreference.merchant_id == self._owner.merchant_id,
                CustomerMemoryPreference.buyer_key == self._owner.buyer_key,
            )
        )
        return result is not False

    async def snapshot(self) -> tuple[bool, int]:
        row = await self._locked_preference()
        return row.memory_enabled, row.memory_generation

    async def write(
        self,
        *,
        category: str,
        key: str,
        value: str,
        at: datetime,
        source_order: int = 0,
        expected_generation: int | None = None,
    ) -> CustomerMemory | None:
        fact = SimpleNamespace(category=category, key=key, value=value)
        if not category or not key or not value or filter_candidate(fact).rejected:
            return None
        preference = await self._locked_preference()
        if not preference.memory_enabled or (
            expected_generation is not None and preference.memory_generation != expected_generation
        ):
            return None
        if filter_persisted(fact).rejected:
            return None
        row_id = await self._session.scalar(
            pg_insert(CustomerMemory)
            .values(
                id=uuid4(),
                merchant_id=self._owner.merchant_id,
                buyer_key=self._owner.buyer_key,
                category=category,
                key=key,
                value=value,
                last_confirmed_at=at,
                source_order=source_order,
            )
            .on_conflict_do_update(
                constraint="uq_customer_memories_owner_key",
                # 唯一键含 category（迁移 20261001_0046）：同类同 key 才视为同一事实并更新。
                set_={"value": value, "last_confirmed_at": at, "source_order": source_order},
                where=or_(
                    CustomerMemory.last_confirmed_at < at,
                    and_(
                        CustomerMemory.last_confirmed_at == at,
                        CustomerMemory.source_order <= source_order
                        if source_order == 0
                        else CustomerMemory.source_order < source_order,
                    ),
                ),
            )
            .returning(CustomerMemory.id)
        )
        if row_id is None:
            return None
        row = await self._session.get(CustomerMemory, row_id)
        assert row is not None
        await self._session.refresh(row)
        return row

    async def recall(
        self,
        *,
        at: datetime,
        limit: int = 20,
        category: str | None = None,
        exclude_ids: tuple[str, ...] = (),
    ) -> list[CustomerMemory]:
        if not await self.memory_enabled():
            return []
        statement = select(CustomerMemory).where(
            CustomerMemory.merchant_id == self._owner.merchant_id,
            CustomerMemory.buyer_key == self._owner.buyer_key,
            CustomerMemory.last_confirmed_at > at - RETENTION,
        )
        if category is not None:
            statement = statement.where(CustomerMemory.category == category)
        if exclude_ids:
            statement = statement.where(CustomerMemory.id.not_in([UUID(i) for i in exclude_ids]))
        rows = await self._session.scalars(
            statement.order_by(
                CustomerMemory.last_confirmed_at.desc(), CustomerMemory.id.desc()
            ).limit(limit)
        )
        return list(rows.all())

    async def directory(self, *, at: datetime) -> list[dict[str, object]]:
        if not await self.memory_enabled():
            return []
        rows = await self._session.execute(
            select(CustomerMemory.category, func.max(CustomerMemory.last_confirmed_at).label("at"))
            .where(
                CustomerMemory.merchant_id == self._owner.merchant_id,
                CustomerMemory.buyer_key == self._owner.buyer_key,
                CustomerMemory.last_confirmed_at > at - RETENTION,
            )
            .group_by(CustomerMemory.category)
            .order_by(func.max(CustomerMemory.last_confirmed_at).desc(), CustomerMemory.category)
            .limit(21)
        )
        return [
            {"category": category, "last_confirmed_at": confirmed.isoformat()}
            for category, confirmed in rows
        ]

    async def delete(self, *, memory_id: UUID) -> bool:
        preference = await self._locked_preference()
        result = await self._session.execute(
            delete(CustomerMemory)
            .where(
                CustomerMemory.id == memory_id,
                CustomerMemory.merchant_id == self._owner.merchant_id,
                CustomerMemory.buyer_key == self._owner.buyer_key,
            )
            .returning(CustomerMemory.id)
        )
        deleted = result.scalar_one_or_none() is not None
        if deleted:
            preference.memory_generation += 1
            await self._session.flush()
        return deleted

    async def set_preference(self, *, enabled: bool) -> int:
        preference = await self._locked_preference()
        if preference.memory_enabled != enabled:
            preference.memory_generation += 1
        preference.memory_enabled = enabled
        purged = 0
        if not enabled:
            result = await self._session.execute(
                delete(CustomerMemory)
                .where(
                    CustomerMemory.merchant_id == self._owner.merchant_id,
                    CustomerMemory.buyer_key == self._owner.buyer_key,
                )
                .returning(CustomerMemory.id)
            )
            purged = len(result.scalars().all())
        await self._session.flush()
        return purged
