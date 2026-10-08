"""记忆短任务对保留期和陈旧总结的确定性处理。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.jobs.purge_expired_customer_memory import purge_once
from app.jobs.rebuild_memory_summaries import rebuild_once
from app.models.memory_v2 import CustomerMemory, MerchantMemorySummary
from tests.conftest import MERCHANT_ONE_ID
from tests.support.memory_owners import CustomerStoreFor, MerchantStoreFor

NOW = datetime(2026, 9, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_purge_only_expired_customer_facts(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    store = CustomerStoreFor(db_session)
    await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="preference",
        key="old", value="旧偏好", at=NOW - timedelta(days=181),
    )
    await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="preference",
        key="new", value="新偏好", at=NOW - timedelta(days=179),
    )
    await db_session.commit()
    assert await purge_once(integration_database, now=NOW) == 1
    async with integration_database.session() as session:
        rows = (await session.scalars(select(CustomerMemory))).all()
    assert [row.key for row in rows] == ["new"]


@pytest.mark.asyncio
async def test_rebuild_removes_deleted_fact_from_summary(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    store = MerchantStoreFor(db_session)
    fact = await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="回复语气偏正式",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
    )
    assert fact is not None
    await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)
    await store.delete_fact(merchant_id=MERCHANT_ONE_ID, fact_id=fact.id)
    await db_session.commit()
    assert await rebuild_once(integration_database, now=NOW) == 1
    async with integration_database.session() as session:
        summaries = (await session.scalars(select(MerchantMemorySummary))).all()
    assert summaries == []
