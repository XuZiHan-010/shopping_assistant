"""记忆升级：来源顺序、确认时间及删除/关闭的任务屏障。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionRole
from app.db.session import Database
from app.jobs.drain_memory_outbox import drain_once
from app.llm.fake import FakeLlmClient
from app.memory.pipeline import enqueue_turn
from app.models.memory_v2 import CustomerMemory, MemoryExtractionJob, MerchantMemoryFact
from tests.conftest import MERCHANT_ONE_ID
from tests.integration.v2.test_memory_outbox import _turn
from tests.support.memory_owners import CustomerStoreFor, MerchantStoreFor

NOW = datetime(2026, 10, 13, tzinfo=UTC)


def fake(value: str, *, merchant: bool = False) -> FakeLlmClient:
    import json

    return FakeLlmClient(
        responses=[
            json.dumps(
                {
                    "facts": [
                        {
                            "category": "presentation" if merchant else "preference",
                            "key": "detail" if merchant else "color",
                            "value": value,
                            "source_index": 0,
                            "evidence": value,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        ]
    )


async def drain(database: Database, value: str, *, merchant: bool = False) -> None:
    await drain_once(
        database,
        now=NOW + timedelta(days=3),
        llm_for_job=lambda *_: fake(value, merchant=merchant),
        max_calls=1,
        max_tokens=4000,
        limit=1,
    )


@pytest.mark.parametrize("merchant", [False, True])
async def test_older_job_finishing_later_does_not_restore_old_preference(
    db_session: AsyncSession,
    integration_database: Database,
    merchant_one_id: object,
    merchant: bool,
) -> None:
    role = SessionRole.MERCHANT if merchant else SessionRole.CUSTOMER
    old = "回答详细些" if merchant else "喜欢蓝色"
    new = "回答简短些" if merchant else "喜欢红色"
    first, ctx = await _turn(db_session, buyer_key=None if merchant else "buyer-a", role=role)
    first.content, first.created_at = old, NOW
    await db_session.flush()
    await enqueue_turn(db_session, message=first, ctx=ctx)
    # 先把旧任务租给另一实例，较新的任务先完成。
    job = await db_session.scalar(select(MemoryExtractionJob))
    assert job is not None
    job.status, job.lease_until = "PROCESSING", NOW + timedelta(days=10)
    second, ctx = await _turn(db_session, buyer_key=None if merchant else "buyer-a", role=role)
    second.content, second.created_at = new, NOW + timedelta(minutes=1)
    await db_session.flush()
    await enqueue_turn(db_session, message=second, ctx=ctx)
    await db_session.commit()
    await drain(integration_database, new, merchant=merchant)
    async with integration_database.session() as session:
        await session.execute(
            update(MemoryExtractionJob)
            .where(MemoryExtractionJob.id == job.id)
            .values(status="PENDING")
        )
        await session.commit()
    await drain(integration_database, old, merchant=merchant)
    async with integration_database.session() as session:
        if merchant:
            rows = await MerchantStoreFor(session).facts(merchant_id=MERCHANT_ONE_ID)
            assert [row.content for row in rows] == [new]
            summaries = await MerchantStoreFor(session).active_summaries(
                merchant_id=MERCHANT_ONE_ID
            )
            assert [row.content for row in summaries] == [new]
        else:
            rows = (await session.scalars(select(CustomerMemory))).all()
            assert [row.value for row in rows] == [new]
            assert rows[0].last_confirmed_at == NOW + timedelta(minutes=1)


async def test_disable_then_enable_does_not_allow_previous_job_to_write(
    db_session: AsyncSession,
    integration_database: Database,
    merchant_one_id: object,
) -> None:
    message, ctx = await _turn(db_session, buyer_key="buyer-a")
    message.content = "喜欢蓝色"
    await db_session.flush()
    await enqueue_turn(db_session, message=message, ctx=ctx)
    store = CustomerStoreFor(db_session)
    await store.set_preference(merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", enabled=False)
    await store.set_preference(merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", enabled=True)
    await db_session.commit()
    await drain(integration_database, "喜欢蓝色")
    async with integration_database.session() as session:
        assert list((await session.scalars(select(CustomerMemory))).all()) == []
        assert (await session.scalar(select(MemoryExtractionJob))).status == "DONE"


@pytest.mark.parametrize("merchant", [False, True])
async def test_delete_cancels_previous_jobs_but_new_confirmation_can_write(
    db_session: AsyncSession,
    integration_database: Database,
    merchant_one_id: object,
    merchant: bool,
) -> None:
    value = "回答简短些" if merchant else "喜欢蓝色"
    if merchant:
        store = MerchantStoreFor(db_session)
        row = await store.add_fact(
            merchant_id=MERCHANT_ONE_ID,
            category="presentation",
            content=value,
            source_ref=f"{uuid4()}:{uuid4()}",
            at=NOW,
        )
    else:
        store = CustomerStoreFor(db_session)
        row = await store.write(
            merchant_id=MERCHANT_ONE_ID,
            buyer_key="buyer-a",
            category="appearance",
            key="color",
            value=value,
            at=NOW,
        )
    assert row is not None
    role = SessionRole.MERCHANT if merchant else SessionRole.CUSTOMER
    message, ctx = await _turn(db_session, buyer_key=None if merchant else "buyer-a", role=role)
    message.content = value
    await db_session.flush()
    await enqueue_turn(db_session, message=message, ctx=ctx)
    if merchant:
        assert await store.delete_fact(merchant_id=MERCHANT_ONE_ID, fact_id=row.id)
    else:
        assert await store.delete(
            merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", memory_id=row.id
        )
    await db_session.commit()
    await drain(integration_database, value, merchant=merchant)
    async with integration_database.session() as session:
        if merchant:
            assert await MerchantStoreFor(session).facts(merchant_id=MERCHANT_ONE_ID) == []
        else:
            assert list((await session.scalars(select(CustomerMemory))).all()) == []
        message, ctx = await _turn(session, buyer_key=None if merchant else "buyer-a", role=role)
        message.content = value
        await session.flush()
        await enqueue_turn(session, message=message, ctx=ctx)
        await session.commit()
    await drain(integration_database, value, merchant=merchant)
    async with integration_database.session() as session:
        model = MerchantMemoryFact if merchant else CustomerMemory
        rows = (await session.scalars(select(model))).all()
        active = [r for r in rows if r.deleted_at is None] if merchant else rows
        assert len(active) == 1
