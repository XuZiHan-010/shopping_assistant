"""nonce 的持久化与原子消费（契约 §8.7.9）——必须在真实 PostgreSQL 上验证。

这里回答四个问题，每一个答错都会让「批准只能用一次」名存实亡：
消费是不是真的只成功一次、失败事务里的消费会不会跟着回滚、并发消费会不会两个都赢、
进程重启后同一个 nonce 还能不能再用。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database
from app.models.operations import OperationEvidenceNonce
from app.repositories.v2.operation_evidence import OperationEvidenceRepository
from app.services.v2.approval_evidence import EVIDENCE_PURPOSE

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)


async def _register(session: AsyncSession, nonce: str, *, ttl_minutes: int = 10) -> None:
    await OperationEvidenceRepository(session).register(
        purpose=EVIDENCE_PURPOSE,
        nonce=nonce,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=ttl_minutes),
    )


@pytest.mark.asyncio
async def test_nonce_can_be_consumed_only_once(db_session: AsyncSession) -> None:
    repo = OperationEvidenceRepository(db_session)
    await _register(db_session, "nonce-1")
    await db_session.commit()

    first = await repo.consume(purpose=EVIDENCE_PURPOSE, nonce="nonce-1", now=NOW)
    await db_session.commit()
    second = await repo.consume(purpose=EVIDENCE_PURPOSE, nonce="nonce-1", now=NOW)

    assert (first, second) == (True, False)


@pytest.mark.asyncio
async def test_unknown_nonce_is_not_consumable(db_session: AsyncSession) -> None:
    repo = OperationEvidenceRepository(db_session)

    assert await repo.consume(purpose=EVIDENCE_PURPOSE, nonce="never-issued", now=NOW) is False


@pytest.mark.asyncio
async def test_nonce_of_another_purpose_is_not_consumable(db_session: AsyncSession) -> None:
    """同一张表按用途分区：售后确认的 nonce 不能拿来批准草稿。"""

    repo = OperationEvidenceRepository(db_session)
    await OperationEvidenceRepository(db_session).register(
        purpose="customer-confirmation:v1",
        nonce="shared-nonce",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )
    await db_session.commit()

    assert await repo.consume(purpose=EVIDENCE_PURPOSE, nonce="shared-nonce", now=NOW) is False


@pytest.mark.asyncio
async def test_expired_nonce_is_not_consumable(db_session: AsyncSession) -> None:
    repo = OperationEvidenceRepository(db_session)
    await _register(db_session, "nonce-expired")
    await db_session.commit()

    consumed = await repo.consume(
        purpose=EVIDENCE_PURPOSE, nonce="nonce-expired", now=NOW + timedelta(minutes=11)
    )

    assert consumed is False


@pytest.mark.asyncio
async def test_consumption_rolls_back_with_the_business_transaction(
    integration_database: Database, db_session: AsyncSession
) -> None:
    """§8.7.9 的核心：业务写入失败时证据不能被"吃掉"，否则用户要重新获取证据。"""

    await _register(db_session, "nonce-rollback")
    await db_session.commit()

    async with integration_database.session() as session:
        repo = OperationEvidenceRepository(session)
        assert await repo.consume(purpose=EVIDENCE_PURPOSE, nonce="nonce-rollback", now=NOW)
        await session.rollback()

    async with integration_database.session() as session:
        again = await OperationEvidenceRepository(session).consume(
            purpose=EVIDENCE_PURPOSE, nonce="nonce-rollback", now=NOW
        )
        await session.commit()

    assert again is True


@pytest.mark.asyncio
async def test_concurrent_consumption_has_exactly_one_winner(
    integration_database: Database, db_session: AsyncSession
) -> None:
    await _register(db_session, "nonce-race")
    await db_session.commit()

    async def attempt() -> bool:
        async with integration_database.session() as session:
            consumed = await OperationEvidenceRepository(session).consume(
                purpose=EVIDENCE_PURPOSE, nonce="nonce-race", now=NOW
            )
            await session.commit()
            return consumed

    results = await asyncio.gather(*(attempt() for _ in range(5)))

    assert sum(1 for result in results if result) == 1


@pytest.mark.asyncio
async def test_consumption_survives_a_new_engine(
    migrated_postgres: str, db_session: AsyncSession
) -> None:
    """nonce 在库里，不在内存里：换一个连接池（等价于换一个进程）照样已消费。"""

    await _register(db_session, "nonce-restart")
    await db_session.commit()
    async with db_session.begin_nested():
        assert await OperationEvidenceRepository(db_session).consume(
            purpose=EVIDENCE_PURPOSE, nonce="nonce-restart", now=NOW
        )
    await db_session.commit()

    fresh = Database(
        Settings(
            app_env="test",
            database_url=migrated_postgres,
            frontend_origin="http://localhost:5173",
        )
    )
    try:
        async with fresh.session() as session:
            again = await OperationEvidenceRepository(session).consume(
                purpose=EVIDENCE_PURPOSE, nonce="nonce-restart", now=NOW
            )
            await session.commit()
    finally:
        await fresh.dispose()

    assert again is False
    # A real second interpreter must observe the committed consumption.
    child_code = """
import asyncio, json, sys
from app.core.config import Settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.repositories.v2.operation_evidence import OperationEvidenceRepository
from datetime import datetime
async def main():
    data = json.loads(sys.stdin.read())
    database = Database(Settings(app_env="test", database_url=data["url"],
        frontend_origin="http://localhost:5173", llm_api_key=None))
    try:
        async with database.session() as session:
            used = await OperationEvidenceRepository(session).consume(
                purpose=data["purpose"],
                nonce="nonce-restart",
                now=datetime.fromisoformat(data["now"]),
            )
            await session.commit()
        assert used is False
    finally:
        await database.dispose()
configure_event_loop_policy()
asyncio.run(main())
"""
    # 不用 asyncio 子进程：项目在 Windows 上固定使用 SelectorEventLoop，它不支持子进程传输。
    child = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", child_code],
        input=json.dumps(
            {"url": migrated_postgres, "purpose": EVIDENCE_PURPOSE, "now": NOW.isoformat()}
        ).encode(),
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr.decode(errors="replace")


@pytest.mark.asyncio
async def test_purge_removes_only_expired_unconsumed_rows(db_session: AsyncSession) -> None:
    """清理任务接受 `now` 参数，不读墙钟；已消费的记录留到过期后一并清走。"""

    repo = OperationEvidenceRepository(db_session)
    await _register(db_session, "fresh", ttl_minutes=10)
    await _register(db_session, "stale", ttl_minutes=1)
    await db_session.commit()

    removed = await repo.purge_expired(now=NOW + timedelta(minutes=5))
    await db_session.commit()

    remaining = {
        row.nonce for row in (await db_session.execute(select(OperationEvidenceNonce))).scalars()
    }
    assert removed == 1
    assert remaining == {"fresh"}
