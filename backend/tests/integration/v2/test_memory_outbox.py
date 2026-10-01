"""N4 B outbox 只接收可信已落库回合。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from app.memory.customer_store import CustomerMemoryStore
from app.models.conversation import Conversation, Message
from app.models.memory_v2 import (
    CustomerMemory,
    MemoryExtractionJob,
    MerchantMemoryFact,
    MerchantMemorySummary,
)
from app.models.session import AgentSession
from tests.conftest import MERCHANT_ONE_ID
from tests.support.trade import SHOP, database_of

NOW = datetime(2026, 9, 28, tzinfo=UTC)


async def _turn(
    session: AsyncSession, *, buyer_key: str | None, role: SessionRole = SessionRole.CUSTOMER
) -> tuple[Message, SessionContext]:
    agent = AgentSession(
        token_fingerprint=uuid4().hex.ljust(64, "0"), role=role.value,
        merchant_id=MERCHANT_ONE_ID, buyer_key=buyer_key,
        shop_slug="borough-api-100" if role is SessionRole.CUSTOMER else None,
        issuer_fingerprint="f" * 64 if role is SessionRole.MERCHANT else None,
        expires_at=NOW + timedelta(days=1),
    )
    session.add(agent)
    await session.flush()
    conversation = Conversation(
        merchant_id=MERCHANT_ONE_ID, surface="SHOP" if role is SessionRole.CUSTOMER else "MERCHANT",
        conversation_kind="CHAT",
    )
    session.add(conversation)
    await session.flush()
    message = Message(
        merchant_id=MERCHANT_ONE_ID, conversation_id=conversation.id, role="USER",
        content="我喜欢素色", source_locale="zh-CN", session_record_id=agent.id,
    )
    session.add(message)
    await session.flush()
    return message, SessionContext(
        session_record_id=agent.id, role=role, merchant_id=MERCHANT_ONE_ID,
        buyer_key=buyer_key, shop_slug=agent.shop_slug,
    )


@pytest.mark.asyncio
async def test_guest_turn_never_enqueued_even_if_later_bound(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key=None)
    assert await enqueue_turn(db_session, message=message, ctx=context) is False
    await db_session.execute(
        AgentSession.__table__.update().where(AgentSession.id == context.session_record_id)
        .values(buyer_key="later-bound")
    )
    assert await db_session.scalar(select(func.count()).select_from(MemoryExtractionJob)) == 0


@pytest.mark.asyncio
async def test_bound_turn_enqueues_once_and_disabled_turn_does_not(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    assert await enqueue_turn(db_session, message=message, ctx=context) is True
    assert await enqueue_turn(db_session, message=message, ctx=context) is False
    await CustomerMemoryStore(db_session).set_preference(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", enabled=False
    )
    other, other_context = await _turn(db_session, buyer_key="buyer-a")
    assert await enqueue_turn(db_session, message=other, ctx=other_context) is False
    assert await db_session.scalar(select(func.count()).select_from(MemoryExtractionJob)) == 1


@pytest.mark.asyncio
async def test_merchant_turn_enqueues_without_buyer_identity(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key=None, role=SessionRole.MERCHANT)
    assert await enqueue_turn(db_session, message=message, ctx=context) is True
    job = await db_session.scalar(select(MemoryExtractionJob))
    assert job is not None and job.message_id == message.id


@pytest.mark.asyncio
async def test_chat_persists_outbox_with_the_user_message(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    postgres_app.state.settings.demo_deployment_mode = True
    postgres_app.state.settings.demo_customer_identities = {SHOP: "memory-chat-buyer"}
    fake = FakeLlmClient(turns=[
        LlmTurn(text="好的", tool_calls=[], stop_reason="END_TURN", tokens=10),
        LlmTurn(text="已了解", tool_calls=[], stop_reason="END_TURN", tokens=10),
    ])
    monkeypatch.setattr("app.api.routes.v2.shop_chat.build_guarded_llm", lambda *a, **k: fake)
    session = await postgres_client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    headers = {"X-Session-Id": session.json()["session_id"], "Accept": "application/json"}
    guest = await postgres_client.post(
        "/api/v2/shop/chat", headers=headers,
        json={"message": "我喜欢素色", "client_request_id": "memory-guest"},
    )
    assert guest.status_code == 200, guest.text
    await postgres_client.post("/api/v2/shop/sessions/demo-customer", headers=headers, json={})
    bound = await postgres_client.post(
        "/api/v2/shop/chat", headers=headers,
        json={"message": "我偏好简约风格", "client_request_id": "memory-bound"},
    )
    assert bound.status_code == 200, bound.text
    async with database_of(postgres_app).session() as db:
        jobs = (await db.scalars(select(MemoryExtractionJob))).all()
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_drain_extracts_once_and_marks_job_done(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    assert await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.commit()
    fake = FakeLlmClient(responses=[
        '{"facts":[{"category":"preference","key":"style","value":"喜欢素色",'
        '"source_index":0,"evidence":"我喜欢素色"}]}'
    ])
    assert await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000,
    ) == 1
    assert await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000,
    ) == 0
    async with integration_database.session() as session:
        job = await session.scalar(select(MemoryExtractionJob))
        memories = (await session.scalars(select(CustomerMemory))).all()
    assert job is not None and job.status == "DONE" and job.attempts == 1
    assert len(memories) == 1 and memories[0].value == "喜欢素色"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_failed_extraction_retries_only_to_limit(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.commit()
    fake = FakeLlmClient(behaviour="invalid_json")
    for _ in range(3):
        await drain_once(
            integration_database, now=NOW, llm_for_job=lambda *_: fake,
            max_calls=1, max_tokens=4000, max_attempts=2,
        )
    async with integration_database.session() as session:
        job = await session.scalar(select(MemoryExtractionJob))
    assert job is not None and job.status == "FAILED" and job.attempts == 2
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_expired_lease_can_be_reclaimed(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.execute(
        update(MemoryExtractionJob).values(
            status="PROCESSING", attempts=1, lease_until=NOW - timedelta(minutes=1)
        )
    )
    await db_session.commit()
    fake = FakeLlmClient(responses=['{"facts":[]}'])
    assert await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000,
    ) == 1
    async with integration_database.session() as session:
        job = await session.scalar(select(MemoryExtractionJob))
    assert job is not None and job.status == "DONE" and job.attempts == 2


@pytest.mark.asyncio
async def test_concurrent_drains_claim_once(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.commit()
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowFake(FakeLlmClient):
        async def complete(self, **kwargs: object):  # type: ignore[override]
            entered.set()
            await release.wait()
            return await super().complete(**kwargs)  # type: ignore[arg-type]

    fake = SlowFake(responses=['{"facts":[]}'])
    first = asyncio.create_task(drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000,
    ))
    await asyncio.wait_for(entered.wait(), timeout=5)
    second = await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000,
    )
    release.set()
    assert await first == 1
    assert second == 0
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_merchant_drain_builds_fact_and_summary_in_one_completion(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key=None, role=SessionRole.MERCHANT)
    await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.commit()
    fake = FakeLlmClient(responses=[
        '{"facts":[{"category":"tone","key":"style","value":"喜欢素色",'
        '"source_index":0,"evidence":"我喜欢素色"}]}'
    ])
    assert await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000,
    ) == 1
    async with integration_database.session() as session:
        facts = (await session.scalars(select(MerchantMemoryFact))).all()
        summaries = (await session.scalars(select(MerchantMemorySummary))).all()
    assert len(facts) == 1 and len(summaries) == 1
    assert summaries[0].source_fact_ids == [str(facts[0].id)]
    assert summaries[0].is_stale is False


@pytest.mark.asyncio
async def test_disabling_after_queue_prevents_customer_write(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    await enqueue_turn(db_session, message=message, ctx=context)
    await CustomerMemoryStore(db_session).set_preference(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", enabled=False,
    )
    await db_session.commit()
    fake = FakeLlmClient(responses=[
        '{"facts":[{"category":"preference","key":"style","value":"喜欢素色",'
        '"source_index":0,"evidence":"我喜欢素色"}]}'
    ])
    await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000,
    )
    async with integration_database.session() as session:
        assert (await session.scalars(select(CustomerMemory))).all() == []
