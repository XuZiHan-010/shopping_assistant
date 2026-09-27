"""对话来源状态仓储：不跨对话、不跨店铺、不跨对象类型扩散（真实 PostgreSQL）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_config import JobSettings
from app.db.session import Database
from app.jobs.purge_guest_provenance import run_purge
from app.models.provenance import ConversationProvenance
from app.repositories.provenance import (
    MAX_RETRIES,
    ConversationProvenanceRepository,
    ProvenanceWriteConflictError,
)
from app.repositories.session import SessionRepository

PRINCIPAL_KIND = "GUEST_SESSION"
PRINCIPAL_ID = "principal-1"
_SCOPE: dict[str, Any] = {
    "principal_kind": PRINCIPAL_KIND,
    "principal_id": PRINCIPAL_ID,
    "conversation_id": "c-same",
    "object_type": "PRODUCT",
    "object_id": "p-same",
}


def _repo(session: AsyncSession) -> ConversationProvenanceRepository:
    return ConversationProvenanceRepository(session)


@pytest.mark.asyncio
async def test_provenance_does_not_leak_across_conversations(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    await repo.record(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-9",
    )

    assert await repo.has(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-9",
    )
    assert not await repo.has(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c2",
        object_type="PRODUCT",
        object_id="p-9",
    )


@pytest.mark.asyncio
async def test_provenance_does_not_leak_across_shops(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    repo = _repo(db_session)
    await repo.record(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-9",
    )

    assert not await repo.has(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_two_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-9",
    )


@pytest.mark.asyncio
async def test_provenance_does_not_collide_across_object_types(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    await repo.record(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="same",
    )

    assert not await repo.has(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="ORDER",
        object_id="same",
    )


@pytest.mark.asyncio
async def test_concurrent_write_of_different_objects_both_succeed(
    integration_database: Database, db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    # 并发写入用各自独立的连接/事务，必须先提交商家行，否则另一条连接在
    # READ COMMITTED 隔离级别下看不到本事务尚未提交的行，会撞外键。
    await db_session.commit()

    async def write(object_id: str) -> None:
        async with integration_database.session() as session:
            await ConversationProvenanceRepository(session).record(
                principal_kind=PRINCIPAL_KIND,
                principal_id=PRINCIPAL_ID,
                merchant_id=merchant_one_id,
                conversation_id="c1",
                object_type="PRODUCT",
                object_id=object_id,
            )
            await session.commit()

    await asyncio.gather(write("p-1"), write("p-2"))

    repo = _repo(db_session)
    assert await repo.has(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-1",
    )
    assert await repo.has(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-2",
    )


@pytest.mark.asyncio
async def test_repeated_record_is_idempotent_and_bumps_version(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)

    async def record_once() -> None:
        await repo.record(
            principal_kind=PRINCIPAL_KIND,
            principal_id=PRINCIPAL_ID,
            merchant_id=merchant_one_id,
            conversation_id="c1",
            object_type="PRODUCT",
            object_id="p-9",
        )

    await record_once()
    await record_once()
    await record_once()

    rows = (
        (
            await db_session.execute(
                select(ConversationProvenance).where(
                    ConversationProvenance.object_id == "p-9",
                    ConversationProvenance.conversation_id == "c1",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].version == 3


@pytest.mark.asyncio
async def test_concurrent_writes_of_same_object_do_not_lose_version_bumps(
    integration_database: Database, db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """同一唯一键上的并发首写与续写：版本号条件更新让每次写入都被计数，不互相覆盖。"""

    await db_session.commit()

    async def write() -> None:
        async with integration_database.session() as session:
            repo = ConversationProvenanceRepository(session)
            await repo.record(**_SCOPE, merchant_id=merchant_one_id)
            await session.commit()

    await asyncio.gather(write(), write(), write())

    version = await db_session.scalar(
        select(ConversationProvenance.version).where(
            ConversationProvenance.object_id == _SCOPE["object_id"]
        )
    )
    assert version == 3


class _AlwaysStaleRepository(ConversationProvenanceRepository):
    """每次都读到过期版本号，模拟持续被其他写入抢先。"""

    reads = 0

    async def _current_version(self, scope: Any) -> int | None:
        self.reads += 1
        return 0


@pytest.mark.asyncio
async def test_version_conflict_retries_are_bounded(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _repo(db_session).record(**_SCOPE, merchant_id=merchant_one_id)
    repo = _AlwaysStaleRepository(db_session)

    with pytest.raises(ProvenanceWriteConflictError):
        await repo.record(**_SCOPE, merchant_id=merchant_one_id)

    assert repo.reads == MAX_RETRIES + 1
    version = await db_session.scalar(
        select(ConversationProvenance.version).where(
            ConversationProvenance.object_id == _SCOPE["object_id"]
        )
    )
    assert version == 1  # 冲突时不盲写


@pytest.mark.asyncio
async def test_purge_removes_only_expired_unbound_guest_provenance(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    sessions = SessionRepository(db_session, default_ttl_seconds=86_400)
    _, expired_guest = await sessions.issue_customer_guest(
        merchant_id=merchant_one_id, shop_slug="s", ttl_seconds=-1
    )
    _, live_guest = await sessions.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")
    _, expired_bound = await sessions.issue_customer_guest(
        merchant_id=merchant_one_id, shop_slug="s", ttl_seconds=-1
    )
    await sessions.bind_demo_customer(expired_bound, buyer_key="bk-1")

    repo = _repo(db_session)
    for ctx in (expired_guest, live_guest, expired_bound):
        await repo.record(
            principal_kind="GUEST_SESSION",
            principal_id=str(ctx.session_record_id),
            merchant_id=merchant_one_id,
            conversation_id="c1",
            object_type="PRODUCT",
            object_id="p-1",
        )
    await repo.record(
        principal_kind="BOUND_PRINCIPAL",
        principal_id="bound-digest",
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-1",
    )

    assert await repo.purge_expired_unbound_guests(now=datetime.now(UTC)) == 1
    remaining = set(
        (await db_session.execute(select(ConversationProvenance.principal_id))).scalars()
    )
    assert remaining == {
        str(live_guest.session_record_id),
        str(expired_bound.session_record_id),
        "bound-digest",
    }
    # 幂等：再跑一次不再删除任何行。
    assert await repo.purge_expired_unbound_guests(now=datetime.now(UTC)) == 0


@pytest.mark.asyncio
async def test_purge_job_commits_through_its_own_database(
    integration_database: Database,
    migrated_postgres: str,
    db_session: AsyncSession,
    merchant_one_id: UUID,
) -> None:
    sessions = SessionRepository(db_session, default_ttl_seconds=86_400)
    _, expired_guest = await sessions.issue_customer_guest(
        merchant_id=merchant_one_id, shop_slug="s", ttl_seconds=-1
    )
    await _repo(db_session).record(
        principal_kind="GUEST_SESSION",
        principal_id=str(expired_guest.session_record_id),
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-1",
    )
    await db_session.commit()

    deleted = await run_purge(JobSettings(database_url=migrated_postgres))

    assert deleted == 1
    async with integration_database.session() as session:
        assert await session.scalar(select(ConversationProvenance.id)) is None


@pytest.mark.asyncio
async def test_delete_for_conversation_clears_only_that_conversation(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    await repo.record(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-9",
    )
    await repo.record(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c2",
        object_type="PRODUCT",
        object_id="p-9",
    )

    await repo.delete_for_conversation(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
    )

    assert not await repo.has(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c1",
        object_type="PRODUCT",
        object_id="p-9",
    )
    assert await repo.has(
        principal_kind=PRINCIPAL_KIND,
        principal_id=PRINCIPAL_ID,
        merchant_id=merchant_one_id,
        conversation_id="c2",
        object_type="PRODUCT",
        object_id="p-9",
    )
