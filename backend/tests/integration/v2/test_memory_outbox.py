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
from app.models.conversation import Conversation, Message
from app.models.memory_v2 import (
    CustomerMemory,
    MemoryExtractionJob,
    MerchantMemoryFact,
    MerchantMemorySummary,
)
from app.models.session import AgentSession
from tests.conftest import MERCHANT_ONE_ID
from tests.support.memory_owners import CustomerStoreFor
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
    await CustomerStoreFor(db_session).set_preference(
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
async def test_expired_lease_at_attempt_limit_fails_without_calling_model(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    """审查 I4：最后一次尝试时进程被杀（_fail 没执行），回收时不得再发起调用，直接判失败。"""

    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.execute(
        update(MemoryExtractionJob).values(
            status="PROCESSING", attempts=2, lease_until=NOW - timedelta(minutes=1)
        )
    )
    await db_session.commit()
    fake = FakeLlmClient(responses=['{"facts":[]}'])

    await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000, max_attempts=2,
    )

    async with integration_database.session() as session:
        job = await session.scalar(select(MemoryExtractionJob))
    assert job is not None and job.status == "FAILED" and job.attempts == 2
    assert job.last_error == "LeaseExpired"
    assert fake.calls == []


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
    await CustomerStoreFor(db_session).set_preference(
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


@pytest.mark.asyncio
async def test_drain_skips_row_locked_by_another_claimer(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    """台账 M1：另一个排空实例正持有行锁时，本实例跳过该行（SKIP LOCKED），既不阻塞也不重复领取。"""

    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.commit()
    fake = FakeLlmClient(responses=['{"facts":[]}'])
    async with integration_database.session() as holder:
        await holder.execute(select(MemoryExtractionJob).with_for_update())  # 持锁不提交
        drained = await asyncio.wait_for(
            drain_once(
                integration_database, now=NOW, llm_for_job=lambda *_: fake,
                max_calls=1, max_tokens=4000,
            ),
            timeout=5,
        )
        await holder.rollback()
    assert drained == 0 and fake.calls == []


@pytest.mark.asyncio
async def test_later_jobs_are_not_leased_while_earlier_one_runs(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    """台账 M2：逐个领取——后排任务在轮到之前保持 PENDING，租约不会在等待中耗尽而被别的实例重领。"""

    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    for buyer in ("buyer-a", "buyer-b"):
        message, context = await _turn(db_session, buyer_key=buyer)
        await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.commit()
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowFake(FakeLlmClient):
        async def complete(self, **kwargs: object):  # type: ignore[override]
            entered.set()
            await release.wait()
            return await super().complete(**kwargs)  # type: ignore[arg-type]

    fake = SlowFake(responses=['{"facts":[]}', '{"facts":[]}'])
    task = asyncio.create_task(drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000,
    ))
    await asyncio.wait_for(entered.wait(), timeout=5)
    async with integration_database.session() as session:
        statuses = sorted(
            (await session.scalars(select(MemoryExtractionJob.status))).all()
        )
    release.set()
    assert await task == 2
    assert statuses == ["PENDING", "PROCESSING"]


@pytest.mark.asyncio
async def test_lease_starts_when_each_job_is_actually_claimed(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    """复审 F2：一批里排在后面的任务，租约按它被领取时的时钟算，而不是按排空入口的时刻——
    否则前面的模型调用慢一点，后面的任务一领到租约就已过期，会被别的实例重领、重复计费。"""

    from app.jobs.drain_memory_outbox import LEASE, drain_once
    from app.memory.pipeline import enqueue_turn

    for buyer in ("buyer-a", "buyer-b"):
        message, context = await _turn(db_session, buyer_key=buyer)
        await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.commit()
    ticks = iter([NOW, NOW + timedelta(seconds=400), NOW + timedelta(seconds=800)])
    leases: list[datetime] = []

    class LeaseProbe(FakeLlmClient):
        async def complete(self, **kwargs: object):  # type: ignore[override]
            async with integration_database.session() as session:
                leases.append(await session.scalar(
                    select(MemoryExtractionJob.lease_until)
                    .where(MemoryExtractionJob.status == "PROCESSING")
                ))
            return await super().complete(**kwargs)  # type: ignore[arg-type]

    fake = LeaseProbe(responses=['{"facts":[]}', '{"facts":[]}'])
    assert await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000, clock=lambda: next(ticks),
    ) == 2
    assert leases == [NOW + LEASE, NOW + timedelta(seconds=400) + LEASE]


@pytest.mark.asyncio
async def test_failed_job_is_not_retried_again_within_the_same_drain(
    db_session: AsyncSession, integration_database: Database, merchant_one_id: object
) -> None:
    """复核 Minor-B：失败退回 PENDING 的任务留给下一次排空，不在同一轮里紧接着重试——
    限流、超时这类暂时性错误不应在一次排空里连续耗尽全部重试次数。"""

    from app.jobs.drain_memory_outbox import drain_once
    from app.memory.pipeline import enqueue_turn

    message, context = await _turn(db_session, buyer_key="buyer-a")
    await enqueue_turn(db_session, message=message, ctx=context)
    await db_session.commit()
    fake = FakeLlmClient(behaviour="invalid_json")
    await drain_once(
        integration_database, now=NOW, llm_for_job=lambda *_: fake,
        max_calls=1, max_tokens=4000, max_attempts=2,
    )
    async with integration_database.session() as session:
        job = await session.scalar(select(MemoryExtractionJob))
    assert job is not None and job.status == "PENDING" and job.attempts == 1
    assert len(fake.calls) == 1
