"""Cron 分发器的到期判定（N5 C Task 4；PRD §10.7）——纯函数，不连库。"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path

import pytest

from app.jobs.run_scheduled import (
    BRIEF_PREGENERATION,
    Cadence,
    ScheduledSettings,
    due_jobs,
    exit_code,
    slot_for,
)
from app.knowledge.index_versions import BuildOutcome, BuildResult, IndexFailureReason

T = datetime(2026, 10, 4, 16, 3, 27, tzinfo=UTC)  # 上海 10 月 5 日 00:03


def _settings(**overrides: object) -> ScheduledSettings:
    return ScheduledSettings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+psycopg://user:pass@localhost/test",
        **overrides,
    )


def test_brief_pregeneration_disabled_by_default() -> None:
    # 简报预生成会调用 LLM（R3），默认不在到期清单里。
    assert BRIEF_PREGENERATION not in due_jobs(_settings(), now=T)


def test_slots_floor_to_five_minutes_the_hour_and_the_business_day() -> None:
    assert slot_for(Cadence.EVERY_RUN, T) == datetime(2026, 10, 4, 16, 0, tzinfo=UTC)
    assert slot_for(Cadence.EVERY_RUN, T + timedelta(minutes=2)) == datetime(
        2026, 10, 4, 16, 5, tzinfo=UTC
    )
    assert slot_for(Cadence.HOURLY, T + timedelta(minutes=50)) == datetime(
        2026, 10, 4, 16, 0, tzinfo=UTC
    )
    # 每日任务按业务日（Asia/Shanghai）切：UTC 16:00 就是上海的零点。
    assert slot_for(Cadence.DAILY, T) == datetime(2026, 10, 4, 16, 0, tzinfo=UTC)
    assert slot_for(Cadence.DAILY, T - timedelta(minutes=10)) == datetime(
        2026, 10, 3, 16, 0, tzinfo=UTC
    )


def test_slot_requires_an_aware_datetime() -> None:
    with pytest.raises(ValueError, match="时区"):
        slot_for(Cadence.HOURLY, datetime(2026, 10, 4, 16, 3))


def test_cleanup_jobs_are_always_due_on_a_fresh_database() -> None:
    names = due_jobs(_settings(), now=T)

    assert names[0] == "close_expired_orders"  # 时效最紧的排最前
    for name in (
        "expire_drafts",
        "purge_operation_evidence",
        "rebuild_memory_summaries",
        "chatbi_rollup",
        "purge_machine_translations",
        "purge_guest_provenance",
        "purge_expired_customer_memory",
        "rebuild_projections",
    ):
        assert name in names
    # 需要显式开关或凭证的任务默认不在清单里。
    for name in ("seed_demo_rolling", "drain_memory_outbox", "build_index"):
        assert name not in names


def test_gated_jobs_appear_only_when_their_switch_is_set() -> None:
    names = due_jobs(
        _settings(
            allow_demo_data_refresh=True,
            llm_api_key="sk-test-not-real",
            embedding_model="BAAI/bge-small-zh-v1.5",
        ),
        now=T,
    )

    assert {"seed_demo_rolling", "drain_memory_outbox", "build_index"} <= set(names)
    # 演示数据先滚动，Chat BI 汇总在它之后。
    assert names.index("seed_demo_rolling") < names.index("chatbi_rollup")


def test_a_job_already_run_in_the_current_slot_is_not_due_again() -> None:
    last = {
        "close_expired_orders": slot_for(Cadence.EVERY_RUN, T),
        "expire_drafts": slot_for(Cadence.HOURLY, T) - timedelta(hours=1),
        "chatbi_rollup": slot_for(Cadence.DAILY, T),
    }

    names = due_jobs(_settings(), now=T, last_slots=last)

    assert "close_expired_orders" not in names
    assert "chatbi_rollup" not in names
    assert "expire_drafts" in names  # 上一小时跑过，这一小时还没跑


def test_exit_code_is_non_zero_when_a_job_fails_or_enabled_capability_is_unavailable() -> None:
    assert exit_code({"a": "OK", "b": "NOT_DUE", "c": "DISABLED", "d": "SKIPPED_LOCKED"}) == 0
    assert exit_code({"a": "OK", "b": "FAILED"}) == 1
    assert exit_code({"daily_brief": "UNAVAILABLE"}) == 1


@pytest.mark.asyncio
async def test_failed_index_build_is_reported_as_job_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """构建返回 FAILED 时必须让分发器保留时间片，以便下次重试。"""
    scheduled = import_module("app.jobs.run_scheduled")

    async def failed_build(_database: object, _settings: object) -> BuildOutcome:
        return BuildOutcome(BuildResult.FAILED, 7, IndexFailureReason.QUALITY_REGRESSION)

    monkeypatch.setattr(scheduled, "build_if_needed", failed_build)
    monkeypatch.setattr(scheduled, "Settings", lambda: object())
    context = scheduled.JobContext(
        database=object(),  # type: ignore[arg-type]
        settings=_settings(embedding_model="BAAI/bge-small-zh-v1.5"),
        now=T,
        slot=slot_for(Cadence.HOURLY, T),
        last_slot=None,
    )

    with pytest.raises(RuntimeError, match="knowledge index build failed"):
        await scheduled._build_index(context)


def test_jobs_never_read_the_wall_clock_without_a_timezone() -> None:
    """任务接受 `now` 参数；`datetime.now()` / `date.today()` 会让补跑与测试都不可预测。"""

    pattern = re.compile(r"datetime\.now\(\)|date\.today\(\)")
    jobs = Path(__file__).resolve().parents[3] / "app" / "jobs"
    offenders = [
        path.name
        for path in sorted(jobs.glob("*.py"))
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
