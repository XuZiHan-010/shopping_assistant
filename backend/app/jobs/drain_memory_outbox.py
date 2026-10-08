"""短批次排空记忆任务；由 N5 Cron 接线，本模块可手动调用。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from time import monotonic
from uuid import UUID

from sqlalchemy import and_, or_, select, true

from app.core.config import Settings
from app.core.session import SessionRole
from app.db.session import Database
from app.llm.client import LlmBudget, LlmClient, LlmMessage
from app.memory.customer_store import CustomerMemoryStore
from app.memory.extractor import MemoryCandidate, MemoryExtractor
from app.memory.merchant_store import MerchantMemoryStore
from app.memory.owners import CustomerMemoryOwner, MerchantMemoryOwner
from app.models.conversation import Conversation, Message
from app.models.memory_v2 import MemoryExtractionJob
from app.models.session import AgentSession

LEASE = timedelta(minutes=5)
LlmFactory = Callable[[UUID, SessionRole, UUID], LlmClient]


async def _claim_next(
    database: Database, *, now: datetime, max_attempts: int, skip: frozenset[UUID] = frozenset()
) -> tuple[UUID, int] | None:
    """领取下一项任务；一次只领一项，租约从真正开始处理时算起（台账 M2）。

    批量领取会让排在后面的任务在等待前面的模型调用时耗尽租约，被别的实例重领、重复计费。
    `SKIP LOCKED` 让并发实例跳过彼此正持锁的行，不阻塞也不重复领取。
    """

    while True:
        async with database.session() as session:
            row = await session.scalar(
                select(MemoryExtractionJob)
                .where(or_(
                    MemoryExtractionJob.status == "PENDING",
                    and_(
                        MemoryExtractionJob.status == "PROCESSING",
                        MemoryExtractionJob.lease_until <= now,
                    ),
                ))
                # 本次排空里已处理过的任务不再领（复核 Minor-B）：失败退回 PENDING 的留给
                # 下一次排空，暂时性错误不会在同一轮里紧接着耗尽全部重试次数。
                .where(MemoryExtractionJob.id.not_in(skip) if skip else true())
                .order_by(MemoryExtractionJob.created_at, MemoryExtractionJob.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            if row.status == "PROCESSING" and row.attempts >= max_attempts:
                # 最后一次尝试时进程被杀或调用卡死，_fail 没执行：租约过期后不再重试，
                # 否则崩溃型任务会无限重领、每次都发起一次计费调用。
                row.status = "FAILED"
                row.lease_until = None
                row.last_error = "LeaseExpired"
                await session.commit()
                continue
            row.status = "PROCESSING"
            row.attempts += 1
            row.lease_until = now + LEASE
            row.last_error = None
            claimed = (row.id, row.attempts)
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
            store = CustomerMemoryStore(
                session,
                CustomerMemoryOwner.from_verified_turn(
                    merchant_id=merchant_id, buyer_key=buyer_key
                ),
            )
            for candidate in candidates:
                await store.write(
                    category=candidate.category, key=candidate.key, value=candidate.value, at=now,
                )
        else:
            merchant_store = MerchantMemoryStore(
                session, MerchantMemoryOwner.from_verified_turn(merchant_id=merchant_id)
            )
            changed = False
            for candidate in candidates:
                fact = await merchant_store.add_fact(
                    category=candidate.category,
                    content=candidate.value,
                    source_ref=f"{message.conversation_id}:{message.id}", at=now,
                )
                changed = changed or fact is not None
            if changed:
                await merchant_store.rebuild_summaries(at=now)
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
    clock: Callable[[], datetime] | None = None,
) -> int:
    """逐个领取至多 `limit` 项，模型失败只影响该任务；调用方须提供带每日费用守卫的 LLM。"""

    if not 1 <= limit <= 100 or max_attempts < 1:
        raise ValueError("无效的排空批次或重试上限")
    # 每次领取都重新取时钟（复审 F2）：租约与「是否过期」都按领取那一刻算。缺省为入口时刻加上
    # 实际流逝的单调时间——测试传固定 `now` 时结果不变，生产里排在后面的任务不会一领到就过期。
    if clock is None:
        started = monotonic()

        def clock() -> datetime:
            return now + timedelta(seconds=monotonic() - started)

    extractor = MemoryExtractor()
    processed = 0
    handled: set[UUID] = set()
    while processed < limit:
        claimed_at = clock()
        claimed = await _claim_next(
            database, now=claimed_at, max_attempts=max_attempts, skip=frozenset(handled)
        )
        if claimed is None:
            break
        job_id, attempt = claimed
        handled.add(job_id)
        processed += 1
        try:
            merchant_id, role, buyer_key, message_id, dialogue = await _read_turn(database, job_id)
            llm = llm_for_job(merchant_id, SessionRole(role), job_id)
            candidates = await extractor.extract(
                dialogue, llm=llm, budget=LlmBudget(max_calls=max_calls, max_tokens=max_tokens)
            )
            await _finish(
                database, job_id=job_id, attempt=attempt, now=claimed_at,
                merchant_id=merchant_id, role=role, buyer_key=buyer_key,
                message_id=message_id, candidates=candidates,
            )
        except Exception as exc:
            await _fail(
                database, job_id=job_id, attempt=attempt,
                max_attempts=max_attempts, error=exc,
            )
    return processed


async def drain_configured_once(
    database: Database, *, settings: Settings, now: datetime, limit: int = 20,
) -> int:
    """生产入口：独立单任务额度，且每次调用必经全局每日预算与用量审计。"""
    from app.api.dependencies import build_guarded_llm

    if not settings.llm_api_key:
        raise ValueError("未配置抽取模型，不领取 outbox 任务")
    return await drain_once(
        database, now=now,
        # 记忆抽取按所属角色与店铺计入三级预算（PRD §10.2），单任务额度只是另一层上限。
        llm_for_job=lambda merchant_id, role, job_id: build_guarded_llm(
            settings, database, request_id=f"memory:{job_id}",
            merchant_id=merchant_id, role=role, purpose="MEMORY",
        ),
        max_calls=settings.memory_extraction_max_calls,
        max_tokens=settings.memory_extraction_max_tokens,
        limit=limit,
    )
