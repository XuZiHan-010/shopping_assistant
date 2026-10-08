"""Cron 统一分发器（N5 C Task 4；PRD §10.7）。

`cron` 服务每 5 分钟运行一次 `python -m app.jobs.run_scheduled`。分发器按下表依次检查每个任务在
当前时间片是否已经成功跑过，没跑过就执行：

- **幂等短任务**：每个任务自己保证重复执行无副作用，分发器不替它们兜底；
- **不重叠**：执行前取事务级 advisory lock。Railway 在上一次还没结束时可能再起一次，
  拿不到锁的实例直接跳过该任务（`SKIPPED_LOCKED`）；
- **不读墙钟**：`now` 由入口传入并原样交给任务，测试与补跑都可预测；
- **漏跑追赶**：到期与否看「上次成功的时间片 < 当前时间片」，停多久都只需要恢复后的一次调度；
  清理类任务一次处理全部过期行，窗口类任务（Chat BI 汇总）把窗口起点前移到上次成功那天；
- **失败隔离**：一个任务失败只记录、不推进它的时间片（下次调度重试），不影响后面的任务。

**Cron 只负责清理，不负责正确性。** 订单超时、草稿过期、证据过期、记忆保存期都在各自的业务读写
路径上按截止时间判定；这里迟跑、漏跑，业务结果都不变。

状态表 `scheduled_job_runs` 只存任务名、时间片、结果与异常类别，不含经营数据与异常正文。
"""

from __future__ import annotations

import asyncio
import json
import zlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import text

from app.analytics.dates import business_today
from app.core.config import Settings
from app.core.runtime import configure_event_loop_policy
from app.core.seed_config import SeedSettings
from app.db.session import Database
from app.jobs.build_index import build_if_needed
from app.jobs.close_expired_orders import close_expired_orders
from app.jobs.drain_memory_outbox import drain_configured_once
from app.jobs.expire_drafts import expire_drafts
from app.jobs.purge_expired_customer_memory import purge_once as purge_customer_memory_once
from app.jobs.purge_operation_evidence import purge_operation_evidence
from app.jobs.rebuild_memory_summaries import rebuild_once as rebuild_memory_summaries_once
from app.jobs.rebuild_projections import rebuild_projections
from app.jobs.seed_demo_rolling import roll_forward
from app.knowledge.index_versions import BuildResult
from app.models.operations import ScheduledJobRun
from app.repositories.chatbi import ChatBiRepository
from app.repositories.localization import LocalizationRepository
from app.repositories.provenance import ConversationProvenanceRepository

logger = structlog.get_logger(__name__)

#: 每日简报预生成的开关位。会调用 LLM（R3），默认关闭；本版没有任务模块，开启后只如实报告不可用。
BRIEF_PREGENERATION: Final = "daily_brief"
#: Chat BI 汇总的默认窗口（天）与追赶上限：停得再久，一次调度也只回补这么多天。
DEFAULT_ROLLUP_WINDOW_DAYS: Final = 7
MAX_CATCH_UP_DAYS: Final = 31
#: 顾客记忆清理单次调度最多跑的批数（每批 500 行）。
_MEMORY_PURGE_MAX_BATCHES: Final = 20
_MEMORY_PURGE_BATCH: Final = 500
_LOCK_NAMESPACE: Final = 20261004
_EVERY_RUN_MINUTES: Final = 5


class Cadence(StrEnum):
    EVERY_RUN = "EVERY_RUN"  # 每次调度（5 分钟一个时间片）
    HOURLY = "HOURLY"
    DAILY = "DAILY"  # 按业务日（Asia/Shanghai）


class ScheduledSettings(SeedSettings):
    """分发器自己的配置：只要能连库就能跑清理任务，不需要 Web 服务的密钥。

    三个开关决定受控任务是否启用；其中记忆抽取与索引构建在执行时还要完整的应用配置
    （`Settings`，与 backend 同一组变量），缺失时该任务标为失败而不是悄悄跳过。
    """

    daily_brief_schedule_enabled: bool = False
    llm_api_key: str | None = None
    embedding_model: str | None = None


@dataclass(frozen=True)
class JobContext:
    database: Database
    settings: ScheduledSettings
    now: datetime
    slot: datetime
    #: 上次成功的时间片起点；从未成功过为 None。窗口类任务据此追赶漏跑的日子。
    last_slot: datetime | None


JobRunner = Callable[[JobContext], Awaitable[object]]


def _always(_: ScheduledSettings) -> bool:
    return True


@dataclass(frozen=True)
class ScheduledJob:
    name: str
    cadence: Cadence
    run: JobRunner
    enabled: Callable[[ScheduledSettings], bool] = _always


def slot_for(cadence: Cadence, now: datetime, timezone: str = "Asia/Shanghai") -> datetime:
    """`now` 所在时间片的起点（UTC）。"""

    if now.tzinfo is None:
        raise ValueError("分发器需要带时区的时间")
    utc = now.astimezone(UTC)
    if cadence is Cadence.EVERY_RUN:
        minute = utc.minute - utc.minute % _EVERY_RUN_MINUTES
        return utc.replace(minute=minute, second=0, microsecond=0)
    if cadence is Cadence.HOURLY:
        return utc.replace(minute=0, second=0, microsecond=0)
    day = business_today(utc, timezone=timezone)
    return datetime.combine(day, time(0), ZoneInfo(timezone)).astimezone(UTC)


# ---- 任务实现：全部把 `ctx.now` 原样交给既有任务函数 ------------------------------------------


async def _close_expired_orders(ctx: JobContext) -> object:
    return await close_expired_orders(ctx.database, now=ctx.now)


async def _drain_memory_outbox(ctx: JobContext) -> object:
    # 走真实费用守卫：按所属角色与店铺计入三级预算（PRD §10.2）。
    return await drain_configured_once(ctx.database, settings=Settings(), now=ctx.now)


async def _expire_drafts(ctx: JobContext) -> object:
    return await expire_drafts(ctx.database, now=ctx.now)


async def _purge_operation_evidence(ctx: JobContext) -> object:
    return await purge_operation_evidence(ctx.database, now=ctx.now)


async def _rebuild_memory_summaries(ctx: JobContext) -> object:
    return await rebuild_memory_summaries_once(ctx.database, now=ctx.now)


async def _build_index(ctx: JobContext) -> object:
    # 兜底：知识写入后与 backend 启动时都会重建，这里只在索引仍陈旧时再试一次。
    outcome = await build_if_needed(ctx.database, Settings())
    if outcome is not None and outcome.result is BuildResult.FAILED:
        raise RuntimeError("knowledge index build failed")
    return None if outcome is None else outcome.result.value


async def _seed_demo_rolling(ctx: JobContext) -> object:
    day = business_today(ctx.now, timezone=ctx.settings.business_timezone)
    async with ctx.database.session() as session:
        return await roll_forward(session, settings=ctx.settings, business_day=day)


async def _chatbi_rollup(ctx: JobContext) -> object:
    timezone = ctx.settings.business_timezone
    end = business_today(ctx.now, timezone=timezone)
    start = end - timedelta(days=DEFAULT_ROLLUP_WINDOW_DAYS - 1)
    if ctx.last_slot is not None:
        # 时间片起点是业务日零点，稍后一点取业务日，避开零点边界。
        last_day = business_today(ctx.last_slot + timedelta(hours=1), timezone=timezone)
        start = min(start, last_day)
    start = max(start, end - timedelta(days=MAX_CATCH_UP_DAYS))
    return await ChatBiRepository(ctx.database, business_timezone=timezone).rollup_range(
        start_date=start, end_date=end
    )


async def _purge_machine_translations(ctx: JobContext) -> object:
    async with ctx.database.session() as session:
        deleted = await LocalizationRepository(session).purge_expired_machine(now=ctx.now)
        await session.commit()
        return deleted


async def _purge_guest_provenance(ctx: JobContext) -> object:
    async with ctx.database.session() as session:
        deleted = await ConversationProvenanceRepository(session).purge_expired_unbound_guests(
            now=ctx.now
        )
        await session.commit()
        return deleted


async def _purge_expired_customer_memory(ctx: JobContext) -> object:
    total = 0
    for _ in range(_MEMORY_PURGE_MAX_BATCHES):
        deleted = await purge_customer_memory_once(
            ctx.database, now=ctx.now, limit=_MEMORY_PURGE_BATCH
        )
        total += deleted
        if deleted < _MEMORY_PURGE_BATCH:
            break
    return total


async def _rebuild_projections(ctx: JobContext) -> object:
    """只报告、不修复：自动覆写投影会掩盖写路径的缺陷。"""

    async with ctx.database.session() as session:
        report = await rebuild_projections(session)
    if report.mismatches:
        logger.warning(
            "order_projection_drift", checked=report.checked, mismatches=report.mismatches
        )
    return f"checked={report.checked} mismatches={report.mismatches}"


#: 执行顺序即表中顺序：时效最紧的在前；演示数据先滚动，汇总在它之后。
JOBS: Final[tuple[ScheduledJob, ...]] = (
    ScheduledJob("close_expired_orders", Cadence.EVERY_RUN, _close_expired_orders),
    ScheduledJob(
        "drain_memory_outbox",
        Cadence.EVERY_RUN,
        _drain_memory_outbox,
        # 未配置 Key（R3 未授权）时不领取任务，outbox 留待以后处理。
        enabled=lambda settings: bool(settings.llm_api_key),
    ),
    ScheduledJob("expire_drafts", Cadence.HOURLY, _expire_drafts),
    ScheduledJob("purge_operation_evidence", Cadence.HOURLY, _purge_operation_evidence),
    ScheduledJob("rebuild_memory_summaries", Cadence.HOURLY, _rebuild_memory_summaries),
    ScheduledJob(
        "build_index",
        Cadence.HOURLY,
        _build_index,
        enabled=lambda settings: bool(settings.embedding_model),
    ),
    ScheduledJob(
        "seed_demo_rolling",
        Cadence.DAILY,
        _seed_demo_rolling,
        enabled=lambda settings: settings.allow_demo_data_refresh,
    ),
    ScheduledJob("chatbi_rollup", Cadence.DAILY, _chatbi_rollup),
    ScheduledJob("purge_machine_translations", Cadence.DAILY, _purge_machine_translations),
    ScheduledJob("purge_guest_provenance", Cadence.DAILY, _purge_guest_provenance),
    ScheduledJob("purge_expired_customer_memory", Cadence.DAILY, _purge_expired_customer_memory),
    ScheduledJob("rebuild_projections", Cadence.DAILY, _rebuild_projections),
)


def due_jobs(
    settings: ScheduledSettings,
    *,
    now: datetime,
    last_slots: Mapping[str, datetime] | None = None,
    jobs: Sequence[ScheduledJob] = JOBS,
) -> list[str]:
    """已启用且在当前时间片还没成功跑过的任务名，按执行顺序。"""

    known = last_slots or {}
    due: list[str] = []
    for job in jobs:
        if not job.enabled(settings):
            continue
        last = known.get(job.name)
        if last is None or last < slot_for(job.cadence, now, settings.business_timezone):
            due.append(job.name)
    if settings.daily_brief_schedule_enabled:
        due.append(BRIEF_PREGENERATION)
    return due


def _lock_key(name: str) -> int:
    # 落在 int4 范围内；同名任务恒定同一把锁。
    return zlib.crc32(name.encode()) - 2**31


async def _run_one(
    database: Database, settings: ScheduledSettings, job: ScheduledJob, *, now: datetime
) -> str:
    slot = slot_for(job.cadence, now, settings.business_timezone)
    # 锁、到期判定与状态更新在同一个事务里：锁随事务结束自动释放，进程崩溃也不会留下死锁。
    # 任务本身用自己的连接与事务，失败不会污染这条事务。
    async with database.session() as lock:
        acquired = await lock.scalar(
            text("SELECT pg_try_advisory_xact_lock(:namespace, :key)"),
            {"namespace": _LOCK_NAMESPACE, "key": _lock_key(job.name)},
        )
        if not acquired:
            return "SKIPPED_LOCKED"
        state = await lock.get(ScheduledJobRun, job.name)
        last_slot = state.last_slot if state is not None else None
        if last_slot is not None and last_slot >= slot:
            return "NOT_DUE"

        error: str | None = None
        detail: object = None
        try:
            detail = await job.run(
                JobContext(
                    database=database, settings=settings, now=now, slot=slot, last_slot=last_slot
                )
            )
        except Exception as exc:
            # 只记异常类别：正文可能带连接串、订单号或用户原话。
            error = type(exc).__name__[:120]

        status = "OK" if error is None else "FAILED"
        if state is None:
            state = ScheduledJobRun(
                job_name=job.name, last_status=status, last_run_at=now, run_count=0
            )
            lock.add(state)
        state.last_status = status
        state.last_error = error
        state.last_run_at = now
        state.run_count += 1
        if error is None:
            state.last_slot = slot
        await lock.commit()

    if error is None:
        logger.info("scheduled_job_finished", job=job.name, status=status, detail=str(detail))
    else:
        logger.error("scheduled_job_failed", job=job.name, error=error)
    return status


async def run_scheduled(
    database: Database,
    settings: ScheduledSettings,
    *,
    now: datetime,
    jobs: Sequence[ScheduledJob] = JOBS,
) -> dict[str, str]:
    """依次执行到期任务，返回 `任务名 → 结果`。

    结果取值：`OK`、`FAILED`、`NOT_DUE`（本时间片已成功）、`SKIPPED_LOCKED`（另一个实例正在跑）、
    `DISABLED`（开关未开），以及简报预生成专用的 `UNAVAILABLE`。
    """

    if now.tzinfo is None:
        raise ValueError("分发器需要带时区的时间")
    report: dict[str, str] = {}
    for job in jobs:
        if not job.enabled(settings):
            report[job.name] = "DISABLED"
            continue
        try:
            report[job.name] = await _run_one(database, settings, job, now=now)
        except Exception as exc:
            # 连锁与状态表都够不着（例如连接断开）：记为失败，继续下一个任务。
            logger.error("scheduled_job_failed", job=job.name, error=type(exc).__name__)
            report[job.name] = "FAILED"
    if settings.daily_brief_schedule_enabled:
        # 开关开了但没有任务模块：如实报告，不假装已预生成（R7）。
        logger.warning("daily_brief_pregeneration_unavailable")
        report[BRIEF_PREGENERATION] = "UNAVAILABLE"
    return report


def exit_code(report: Mapping[str, str]) -> int:
    """任务失败或已启用能力不可用时以非零码退出，避免平台误报成功。"""

    return 1 if {"FAILED", "UNAVAILABLE"}.intersection(report.values()) else 0


async def _main() -> int:
    settings = ScheduledSettings()
    database = Database(settings)
    try:
        await database.connect_with_retry()
        report = await run_scheduled(database, settings, now=datetime.now(UTC))
    finally:
        await database.dispose()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return exit_code(report)


def main() -> None:
    configure_event_loop_policy()
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
