"""测试用记忆主体与按调用指定主体的存储适配器（N4-1①）。

生产代码的存储在构造时绑定主体，方法不收 `merchant_id` / `buyer_key`。测试需要在同一用例里
以不同主体（跨商家、跨顾客）调用，这里的适配器每次调用都经 `from_session` 构造一个正确绑定的
存储再转发——走的仍是生产存储与生产主体工厂，只是省去测试里反复构造的样板。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionContext, SessionRole
from app.memory.customer_store import CustomerMemoryStore
from app.memory.merchant_store import MerchantMemoryStore
from app.memory.owners import CustomerMemoryOwner, MerchantMemoryOwner


def customer_owner(merchant_id: UUID, buyer_key: str) -> CustomerMemoryOwner:
    ctx = SessionContext(
        session_record_id=uuid4(), role=SessionRole.CUSTOMER, merchant_id=merchant_id,
        buyer_key=buyer_key, shop_slug="test-shop",
    )
    owner = CustomerMemoryOwner.from_session(ctx)
    assert owner is not None
    return owner


def merchant_owner(merchant_id: UUID) -> MerchantMemoryOwner:
    ctx = SessionContext(
        session_record_id=uuid4(), role=SessionRole.MERCHANT, merchant_id=merchant_id,
        buyer_key=None, shop_slug=None,
    )
    owner = MerchantMemoryOwner.from_session(ctx)
    assert owner is not None
    return owner


class CustomerStoreFor:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _store(self, merchant_id: UUID, buyer_key: str) -> CustomerMemoryStore:
        return CustomerMemoryStore(self._session, customer_owner(merchant_id, buyer_key))

    async def memory_enabled(self, *, merchant_id: UUID, buyer_key: str) -> bool:
        return await self._store(merchant_id, buyer_key).memory_enabled()

    async def write(self, *, merchant_id: UUID, buyer_key: str, **kwargs: Any) -> Any:
        return await self._store(merchant_id, buyer_key).write(**kwargs)

    async def recall(
        self, *, merchant_id: UUID, buyer_key: str, at: datetime, **kwargs: Any
    ) -> Any:
        return await self._store(merchant_id, buyer_key).recall(at=at, **kwargs)

    async def delete(self, *, merchant_id: UUID, buyer_key: str, memory_id: UUID) -> bool:
        return await self._store(merchant_id, buyer_key).delete(memory_id=memory_id)

    async def set_preference(self, *, merchant_id: UUID, buyer_key: str, enabled: bool) -> int:
        return await self._store(merchant_id, buyer_key).set_preference(enabled=enabled)


class MerchantStoreFor:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _store(self, merchant_id: UUID) -> MerchantMemoryStore:
        return MerchantMemoryStore(self._session, merchant_owner(merchant_id))

    async def add_fact(self, *, merchant_id: UUID, **kwargs: Any) -> Any:
        return await self._store(merchant_id).add_fact(**kwargs)

    async def facts(self, *, merchant_id: UUID) -> Any:
        return await self._store(merchant_id).facts()

    async def active_summaries(self, *, merchant_id: UUID) -> Any:
        return await self._store(merchant_id).active_summaries()

    async def rebuild_summaries(self, *, merchant_id: UUID, at: datetime) -> Any:
        return await self._store(merchant_id).rebuild_summaries(at=at)

    async def owned_fact(self, *, merchant_id: UUID, fact_id: UUID) -> Any:
        return await self._store(merchant_id).owned_fact(fact_id=fact_id)

    async def delete_fact(self, *, merchant_id: UUID, fact_id: UUID) -> bool:
        return await self._store(merchant_id).delete_fact(fact_id=fact_id)
