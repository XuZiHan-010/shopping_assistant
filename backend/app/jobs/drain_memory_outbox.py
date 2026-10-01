"""短批次排空记忆任务；由 N5 Cron 接线，本模块可手动调用。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select

from app.core.config import Settings
from app.db.session import Database
from app.llm.client import LlmBudget, LlmClient, LlmMessage
from app.memory.customer_store import CustomerMemoryStore
from app.memory.extractor import MemoryCandidate, MemoryExtractor
from app.memory.merchant_store import MerchantMemoryStore
from app.models.conversation import Conversation, Message
from app.models.memory_v2 import MemoryExtractionJob
from app.models.session import AgentSession

LEASE = timedelta(minutes=5)
LlmFactory = Callable[[UUID, UUID], LlmClient]


async def _claim(database: Database, *, now: datetime, limit: int) -> list[tuple[UUID, int]]:
    async with database.session() as session:
        rows = (await session.scalars(
            select(MemoryExtractionJob)
            .where(or_(
                MemoryExtractionJob.status == "PENDING",
                and_(
                    MemoryExtractionJob.status == "PROCESSING",
                    MemoryExtractionJob.lease_until <= now,
                ),
            ))
            .order_by(MemoryExtractionJob.created_at, MemoryExtractionJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )).all()
        claimed = []
        for row in rows:
            row.status = "PROCESSING"
            row.attempts += 1
            row.lease_until = now + LEASE
            row.last_error = None
            claimed.append((row.id, row.attempts))
        await session.commit()
        return claimed


async def _read_turn(
    database: Database, job_id: UUID
) -> tuple[UUID, str, str | None, UUID, list[LlmMessage]]:
    async with database.session() as session:
        job = await session.get(MemoryExtractionJob, job_id)
        message = await session.get(Message, job.message_id) if job else None
        conversation = await session.get(Conversation, message.conversation_id) if message else None
        agent = (
            await session.get(AgentSession, message.session_record_id)
            if message and message.session_record_id else None
        )
        if (
            job is None or message is None or conversation is None or agent is None
            or message.role != "USER"
            or message.merchant_id != conversation.merchant_id
            or agent.merchant_id != conversation.merchant_id
            or conversation.surface != ("SHOP" if agent.role == "CUSTOMER" else "MERCHANT")
            or (agent.role == "CUSTOMER" and agent.buyer_key is None)
        ):
            raise ValueError("invalid_turn_identity")
        previous = await session.scalar(
            select(Message)
            .where(
                Message.conversation_id == message.conversation_id,
                Message.merchant_id == message.merchant_id,
                Message.role == "ASSISTANT",
                Message.created_at < message.created_at,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        dialogue = []
        if previous is not None:
            dialogue.append(LlmMessage(role="assistant", content=previous.content))
        dialogue.append(LlmMessage(role="user", content=message.content))
        return agent.merchant_id, agent.role, agent.buyer_key, message.id, dialogue


async def _finish(
    database: Database, *, job_id: UUID, attempt: int, now: datetime,
    merchant_id: UUID, role: str, buyer_key: str | None, message_id: UUID,
    candidates: list[MemoryCandidate],
) -> None:
    async with database.session() as session:
        job = await session.scalar(
            select(MemoryExtractionJob)
            .where(MemoryExtractionJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status != "PROCESSING" or job.attempts != attempt:
            return
        message = await session.get(Message, message_id)
        if message is None:
            raise ValueError("missing_turn")
        if role == "CUSTOMER":
            assert buyer_key is not None
            store = CustomerMemoryStore(session)
            for candidate in candidates:
                await store.write(
                    merchant_id=merchant_id, buyer_key=buyer_key,
                    category=candidate.category, key=candidate.key,
                    value=candidate.value, at=now,
                )
        else:
            merchant_store = MerchantMemoryStore(session)
            changed = False
            for candidate in candidates:
                fact = await merchant_store.add_fact(
                    merchant_id=merchant_id, category=candidate.category,
                    content=candidate.value,
                    source_ref=f"{message.conversation_id}:{message.id}", at=now,
                )
                changed = changed or fact is not None
            if changed:
                await merchant_store.rebuild_summaries(merchant_id=merchant_id, at=now)
        job.status = "DONE"
        job.lease_until = None
        await session.commit()


async def _fail(
    database: Database, *, job_id: UUID, attempt: int,
    max_attempts: int, error: Exception,
) -> None:
    async with database.session() as session:
        job = await session.scalar(
            select(MemoryExtractionJob)
            .where(MemoryExtractionJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status != "PROCESSING" or job.attempts != attempt:
            return
        job.status = "FAILED" if attempt >= max_attempts else "PENDING"
        job.lease_until = None
        # 错误正文可能带用户原话，只记录类别，不写入隐私或完整模型输出。
        job.last_error = type(error).__name__[:500]
        await session.commit()


async def drain_once(
    database: Database, *, now: datetime, llm_for_job: LlmFactory,
    max_calls: int, max_tokens: int, max_attempts: int = 2, limit: int = 20,
) -> int:
    """领取固定快照，模型失败只影响任务；调用方须提供带每日费用守卫的 LLM。"""

    if not 1 <= limit <= 100 or max_attempts < 1:
        raise ValueError("无效的排空批次或重试上限")
    claimed = await _claim(database, now=now, limit=limit)
    extractor = MemoryExtractor()
    for job_id, attempt in claimed:
        try:
            merchant_id, role, buyer_key, message_id, dialogue = await _read_turn(database, job_id)
            llm = llm_for_job(merchant_id, job_id)
            candidates = await extractor.extract(
                dialogue, llm=llm, budget=LlmBudget(max_calls=max_calls, max_tokens=max_tokens)
            )
            await _finish(
                database, job_id=job_id, attempt=attempt, now=now,
                merchant_id=merchant_id, role=role, buyer_key=buyer_key,
                message_id=message_id, candidates=candidates,
            )
        except Exception as exc:
            await _fail(
                database, job_id=job_id, attempt=attempt,
                max_attempts=max_attempts, error=exc,
            )
    return len(claimed)


async def drain_configured_once(
    database: Database, *, settings: Settings, now: datetime, limit: int = 20,
) -> int:
    """生产入口：独立单任务额度，且每次调用必经全局每日预算与用量审计。"""
    from app.api.dependencies import build_guarded_llm

    if not settings.llm_api_key:
        raise ValueError("未配置抽取模型，不领取 outbox 任务")
    return await drain_once(
        database, now=now,
        llm_for_job=lambda merchant_id, job_id: build_guarded_llm(
            settings, database, request_id=f"memory:{job_id}",
            merchant_id=merchant_id, purpose="MEMORY",
        ),
        max_calls=settings.memory_extraction_max_calls,
        max_tokens=settings.memory_extraction_max_tokens,
        limit=limit,
    )
