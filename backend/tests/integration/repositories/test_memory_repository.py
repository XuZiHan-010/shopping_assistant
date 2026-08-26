"""记忆仓储的商家隔离与覆盖写语义。"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.repositories.memory import MerchantMemoryRepository


@pytest_asyncio.fixture
async def merchant(db_session: AsyncSession) -> Merchant:
    merchant = Merchant(
        id=uuid4(),
        merchant_code="memory-repository-merchant-one",
        display_name="记忆仓储商家一",
    )
    db_session.add(merchant)
    await db_session.flush()
    return merchant


@pytest_asyncio.fixture
async def other_merchant(db_session: AsyncSession) -> Merchant:
    merchant = Merchant(
        id=uuid4(),
        merchant_code="memory-repository-merchant-two",
        display_name="记忆仓储商家二",
    )
    db_session.add(merchant)
    await db_session.flush()
    return merchant


@pytest.mark.asyncio
async def test_upsert_overwrites_same_merchant_and_category(
    db_session: AsyncSession,
    merchant: Merchant,
) -> None:
    repository = MerchantMemoryRepository(db_session)

    first = await repository.upsert(merchant_id=merchant.id, category="TRADE", content="第一版")
    await db_session.flush()
    second = await repository.upsert(merchant_id=merchant.id, category="TRADE", content="第二版")
    await db_session.flush()

    assert first.id == second.id
    assert second.content == "第二版"
    assert second.version == 2


@pytest.mark.asyncio
async def test_list_for_merchant_never_returns_other_merchants(
    db_session: AsyncSession,
    merchant: Merchant,
    other_merchant: Merchant,
) -> None:
    repository = MerchantMemoryRepository(db_session)
    await repository.upsert(merchant_id=merchant.id, category="TRADE", content="本商家")
    await repository.upsert(merchant_id=other_merchant.id, category="TRADE", content="他人")
    await db_session.flush()

    rows = await repository.list_for_merchant(merchant.id, "TRADE")

    assert [row.content for row in rows] == ["本商家"]


@pytest.mark.asyncio
async def test_archived_memory_is_not_returned(
    db_session: AsyncSession,
    merchant: Merchant,
) -> None:
    repository = MerchantMemoryRepository(db_session)
    memory = await repository.upsert(merchant_id=merchant.id, category="TRADE", content="旧记忆")
    memory.status = "ARCHIVED"
    await db_session.flush()

    assert await repository.list_for_merchant(merchant.id, "TRADE") == []


@pytest.mark.asyncio
async def test_list_all_for_merchant_spans_every_category(
    db_session: AsyncSession,
    merchant: Merchant,
) -> None:
    """闸门打分（`KnowledgeRetrieval.score_question`）运行时业务分类尚未确定，
    必须一次拿到该商家所有分类的记忆，而不是像 `list_for_merchant` 那样按分类过滤。
    """

    repository = MerchantMemoryRepository(db_session)
    await repository.upsert(merchant_id=merchant.id, category="TRADE", content="交易记忆")
    await repository.upsert(merchant_id=merchant.id, category="REFUND", content="退款记忆")
    await db_session.flush()

    rows = await repository.list_all_for_merchant(merchant.id)

    assert {row.content for row in rows} == {"交易记忆", "退款记忆"}


@pytest.mark.asyncio
async def test_list_all_for_merchant_never_returns_other_merchants(
    db_session: AsyncSession,
    merchant: Merchant,
    other_merchant: Merchant,
) -> None:
    repository = MerchantMemoryRepository(db_session)
    await repository.upsert(merchant_id=merchant.id, category="TRADE", content="本商家")
    await repository.upsert(merchant_id=other_merchant.id, category="TRADE", content="他人")
    await db_session.flush()

    rows = await repository.list_all_for_merchant(merchant.id)

    assert [row.content for row in rows] == ["本商家"]


@pytest.mark.asyncio
async def test_list_all_for_merchant_excludes_archived(
    db_session: AsyncSession,
    merchant: Merchant,
) -> None:
    repository = MerchantMemoryRepository(db_session)
    memory = await repository.upsert(merchant_id=merchant.id, category="TRADE", content="旧记忆")
    memory.status = "ARCHIVED"
    await db_session.flush()

    assert await repository.list_all_for_merchant(merchant.id) == []
