from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.core.job_config import JobSettings
from app.jobs import chatbi_rollup
from app.jobs.chatbi_rollup import DEFAULT_WINDOW_DAYS, default_window


def _settings() -> JobSettings:
    return JobSettings(database_url="postgresql+psycopg://user:pass@localhost/demo")


def test_default_window_covers_a_rolling_seven_day_span() -> None:
    """滑动窗口而非只算昨天：迟到的采纳/点赞会改写既往日期的比率，
    每天重刷最近 7 天才能把它们带进汇总。"""

    start, end = default_window(_settings())

    assert isinstance(start, date)
    assert (end - start).days == DEFAULT_WINDOW_DAYS - 1


def test_cli_starts_in_production_with_only_a_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cron Service 只该拿到 DATABASE_URL。

    真实回归：`main()` 原先构造完整 `Settings`，在 `APP_ENV=production` 下会因为
    缺 `FRONTEND_ORIGIN` / `EXPORT_SIGNING_SECRET` 直接启动失败——而汇总任务
    根本用不到这两个值，为了让它起来去注入密钥违反最小权限
    （见 `docs/deployment.md`「演示数据的每日滚动」确立的原则）。
    """

    for leaked in ("FRONTEND_ORIGIN", "EXPORT_SIGNING_SECRET", "LLM_API_KEY", "ADMIN_TOKEN"):
        monkeypatch.delenv(leaked, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/demo")
    monkeypatch.setattr(chatbi_rollup, "configure_event_loop_policy", lambda: None)
    monkeypatch.setattr("sys.argv", ["chatbi_rollup"])

    captured: dict[str, Any] = {}

    async def fake_run_rollup(settings: Any, *, start_date: date, end_date: date) -> int:
        captured["settings"] = settings
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        return 0

    monkeypatch.setattr(chatbi_rollup, "run_rollup", fake_run_rollup)

    chatbi_rollup.main()

    assert captured["settings"].database_url.endswith("/demo")
    assert (captured["end_date"] - captured["start_date"]).days == DEFAULT_WINDOW_DAYS - 1
    assert not set(type(captured["settings"]).model_fields) & {
        "export_signing_secret",
        "frontend_origin",
        "llm_api_key",
    }
