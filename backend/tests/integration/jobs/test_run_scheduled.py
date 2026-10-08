"""Cron 分发器（N5 C Task 4；PRD §10.7）：重叠不重复执行、失败不阻塞、漏跑追赶、清理任务幂等。

真实 PostgreSQL（advisory lock 与状态表都是数据库行为，替身证明不了）；不调用任何 LLM。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.jobs import run_scheduled as dispatcher
from app.jobs.run_scheduled import (
    Cadence,
    JobContext,
    ScheduledJob,
    ScheduledSettings,
    run_scheduled,
    slot_for,
)
from app.models.after_sales import AfterSaleChallengePreview
from app.models.merchant import Merchant
from app.models.operations import OperationEvidenceNonce, ScheduledJobRun

pytestmark = pytest.mark.integration

T = datetime(2026, 10, 4, 16, 3, tzinfo=UTC)  # 上海 10 月 5 日 00:03


def _settings(**overrides: object) -> ScheduledSettings:
    return ScheduledSettings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+psycopg://user:pass@localhost/test",
        **overrides,
    )


async def _state(database: Database, name: str) -> ScheduledJobRun | None:
    async with database.session() as session:
        return await session.get(ScheduledJobRun, name)


def _job(name: str, run: object, cadence: Cadence = Cadence.EVERY_RUN) -> ScheduledJob:
    return ScheduledJob(name=name, cadence=cadence, run=run)  # type: ignore[arg-type]


async def test_overlapping_runs_do_not_double_execute(
    integration_database: Database, db_session: AsyncSession
) -> None:
    """Railway 上一次没跑完时可能再起一次：同一任务同一时间片只执行一次。"""

    executions = 0

    async def slow(_: JobContext) -> None:
        nonlocal executions
        executions += 1
        await asyncio.sleep(0.3)

    jobs = [_job("close_expired_orders", slow)]

    reports = await asyncio.gather(
        run_scheduled(integration_database, _settings(), now=T, jobs=jobs),
        run_scheduled(integration_database, _settings(), now=T, jobs=jobs),
    )

    assert executions == 1
    assert sorted(report["close_expired_orders"] for report in reports) in (
        ["OK", "SKIPPED_LOCKED"],  # 第二个实例没拿到锁
        ["NOT_DUE", "OK"],  # 第二个实例等第一个跑完才检查，发现这个时间片已完成
    )
    state = await _state(integration_database, "close_expired_orders")
    assert state is not None and state.run_count == 1
    assert state.last_slot == slot_for(Cadence.EVERY_RUN, T)


async def test_one_failing_job_does_not_block_others(
    integration_database: Database, db_session: AsyncSession
) -> None:
    ran: list[str] = []

    async def boom(_: JobContext) -> None:
        raise RuntimeError("postgresql://user:secret@db/internal 细节不得落库")

    async def fine(ctx: JobContext) -> None:
        ran.append(ctx.now.isoformat())

    jobs = [_job("chatbi_rollup", boom), _job("close_expired_orders", fine)]

    report = await run_scheduled(integration_database, _settings(), now=T, jobs=jobs)

    assert report == {"chatbi_rollup": "FAILED", "close_expired_orders": "OK"}
    assert ran == [T.isoformat()]
    failed = await _state(integration_database, "chatbi_rollup")
    assert failed is not None
    assert failed.last_status == "FAILED"
    # 失败不推进时间片：下一次调度（同一时间片内）会重试；只记异常类别，不记正文。
    assert failed.last_slot is None
    assert failed.last_error == "RuntimeError"

    again = await run_scheduled(integration_database, _settings(), now=T, jobs=jobs)

    assert again == {"chatbi_rollup": "FAILED", "close_expired_orders": "NOT_DUE"}
    retried = await _state(integration_database, "chatbi_rollup")
    assert retried is not None and retried.run_count == 2


async def test_a_new_slot_makes_the_job_due_again(
    integration_database: Database, db_session: AsyncSession
) -> None:
    seen: list[datetime | None] = []

    async def record(ctx: JobContext) -> None:
        seen.append(ctx.last_slot)

    jobs = [_job("expire_drafts", record, Cadence.HOURLY)]

    first = await run_scheduled(integration_database, _settings(), now=T, jobs=jobs)
    same_hour = await run_scheduled(
        integration_database, _settings(), now=T + timedelta(minutes=20), jobs=jobs
    )
    next_hour = await run_scheduled(
        integration_database, _settings(), now=T + timedelta(hours=1), jobs=jobs
    )

    assert (first, same_hour, next_hour) == (
        {"expire_drafts": "OK"},
        {"expire_drafts": "NOT_DUE"},
        {"expire_drafts": "OK"},
    )
    assert seen == [None, slot_for(Cadence.HOURLY, T)]


async def test_missed_days_are_caught_up(
    integration_database: Database, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cron 停了三天后恢复：Chat BI 汇总的窗口从上次成功那天起补到今天，而不是只算今天。"""

    windows: list[tuple[date, date]] = []

    async def fake_rollup(self: object, *, start_date: date, end_date: date) -> int:
        windows.append((start_date, end_date))
        return 0

    monkeypatch.setattr("app.repositories.chatbi.ChatBiRepository.rollup_range", fake_rollup)
    db_session.add(
        ScheduledJobRun(
            job_name="chatbi_rollup",
            last_slot=slot_for(Cadence.DAILY, T - timedelta(days=12)),
            last_status="OK",
            last_run_at=T - timedelta(days=12),
            run_count=1,
        )
    )
    await db_session.commit()
    jobs = [job for job in dispatcher.JOBS if job.name == "chatbi_rollup"]

    report = await run_scheduled(integration_database, _settings(), now=T, jobs=jobs)

    assert report == {"chatbi_rollup": "OK"}
    today = date(2026, 10, 5)
    assert windows == [(today - timedelta(days=12), today)]


async def test_catch_up_window_is_bounded(
    integration_database: Database, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows: list[tuple[date, date]] = []

    async def fake_rollup(self: object, *, start_date: date, end_date: date) -> int:
        windows.append((start_date, end_date))
        return 0

    monkeypatch.setattr("app.repositories.chatbi.ChatBiRepository.rollup_range", fake_rollup)
    jobs = [job for job in dispatcher.JOBS if job.name == "chatbi_rollup"]

    # 从未跑过：按默认 7 天窗口。
    await run_scheduled(integration_database, _settings(), now=T, jobs=jobs)
    # 停了很久：追赶窗口封顶，避免一次汇总拖垮短任务。
    async with integration_database.session() as session:
        state = await session.get(ScheduledJobRun, "chatbi_rollup")
        assert state is not None
        state.last_slot = slot_for(Cadence.DAILY, T - timedelta(days=200))
        await session.commit()
    await run_scheduled(integration_database, _settings(), now=T, jobs=jobs)

    today = date(2026, 10, 5)
    assert windows == [
        (today - timedelta(days=6), today),
        (today - timedelta(days=dispatcher.MAX_CATCH_UP_DAYS), today),
    ]


async def test_expired_evidence_and_its_previews_are_purged(
    integration_database: Database, db_session: AsyncSession
) -> None:
    merchant_id = uuid4()
    db_session.add(Merchant(id=merchant_id, merchant_code="cron-shop", display_name="Cron 店"))
    await db_session.flush()
    for nonce, expires in (
        ("expired-nonce", T - timedelta(minutes=1)),
        ("live-nonce", T + timedelta(minutes=5)),
    ):
        db_session.add(
            OperationEvidenceNonce(
                purpose="AFTER_SALE_CONFIRMATION",
                nonce=nonce,
                issued_at=expires - timedelta(minutes=10),
                expires_at=expires,
            )
        )
        db_session.add(
            AfterSaleChallengePreview(
                nonce=nonce,
                merchant_id=merchant_id,
                buyer_digest="d" * 64,
                status="AVAILABLE",
                text="摘要",
                unavailable_reason=None,
            )
        )
    await db_session.commit()
    jobs = [job for job in dispatcher.JOBS if job.name == "purge_operation_evidence"]

    report = await run_scheduled(integration_database, _settings(), now=T, jobs=jobs)

    assert report == {"purge_operation_evidence": "OK"}
    async with integration_database.session() as session:
        nonces = (await session.scalars(select(OperationEvidenceNonce.nonce))).all()
        previews = (await session.scalars(select(AfterSaleChallengePreview.nonce))).all()
    assert nonces == ["live-nonce"]
    assert previews == ["live-nonce"]


async def test_default_registry_runs_clean_on_an_empty_database_and_is_idempotent(
    integration_database: Database, db_session: AsyncSession
) -> None:
    """默认配置（无演示数据写权限、无 LLM Key、无嵌入模型）下的一次完整调度。

    清理任务全部成功，受开关控制的任务如实标为未启用；同一时间片再跑一次什么都不做。
    """

    report = await run_scheduled(integration_database, _settings(), now=T)

    assert report["seed_demo_rolling"] == "DISABLED"
    assert report["drain_memory_outbox"] == "DISABLED"
    assert report["build_index"] == "DISABLED"
    enabled = {name: status for name, status in report.items() if status != "DISABLED"}
    assert enabled and set(enabled.values()) == {"OK"}, report
    assert dispatcher.BRIEF_PREGENERATION not in report

    again = await run_scheduled(integration_database, _settings(), now=T)

    assert {status for status in again.values()} == {"NOT_DUE", "DISABLED"}
