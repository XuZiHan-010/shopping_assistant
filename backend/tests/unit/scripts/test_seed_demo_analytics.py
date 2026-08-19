"""演示经营数据 Seed 的两道护栏。

脚本开头会 DELETE 掉六张经营表里该商家的全部数据；它跑错环境或按错日期，
后果分别是「删掉真实数据」和「最新一天查不到数据」，两者都不会自己报错。
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType

import pytest

from app.core.config import AppEnvironment, Settings


def _load_seed_module() -> ModuleType:
    """按文件路径加载，不能写 `from scripts.seed_demo_analytics import ...`。

    仓库根和 `backend/` 下各有一个顶层包叫 `scripts`，而 `tests/api/test_chat_fixtures.py`
    会把仓库根插到 `sys.path[0]`——全量跑测试时 `scripts` 先被绑定到仓库根那个包，
    再 import 本脚本就是 ModuleNotFoundError。单独跑本文件时反而正常，这种「只在
    全量运行时炸」的导入最难排查，所以这里直接绕开包名解析。
    """

    path = Path(__file__).resolve().parents[3] / "scripts" / "seed_demo_analytics.py"
    spec = importlib.util.spec_from_file_location("borough_seed_demo_analytics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_seed_module = _load_seed_module()
default_end_date = _seed_module.default_end_date
reject_production = _seed_module.reject_production


def _settings(app_env: AppEnvironment) -> Settings:
    return Settings(
        app_env=app_env,
        database_url="postgresql://user:pass@localhost:5432/borough",
        frontend_origin="http://localhost:5173",  # type: ignore[arg-type]
        export_signing_secret="test-export-signing-secret",
    )


def test_production_is_refused() -> None:
    with pytest.raises(RuntimeError):
        reject_production(_settings(AppEnvironment.PRODUCTION))


@pytest.mark.parametrize("app_env", [AppEnvironment.DEVELOPMENT, AppEnvironment.TEST])
def test_non_production_environments_are_allowed(app_env: AppEnvironment) -> None:
    reject_production(_settings(app_env))


def test_end_date_follows_the_business_timezone_not_the_host_date() -> None:
    """UTC 宿主在 16:00 UTC 之后，业务时区已经是第二天。

    用 `date.today()` 会让最新一天的 `business_date` 落后于业务今天，
    「今天的 GMV」返回空——`app/analytics/dates.py` 的换算是唯一判定点。
    """

    now = datetime(2026, 8, 4, 17, 0, tzinfo=UTC)

    assert default_end_date(now, timezone="Asia/Shanghai") == date(2026, 8, 5)
    assert default_end_date(now, timezone="Asia/Shanghai") != now.date()


def test_full_rebuild_requires_explicit_force_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_seed_module, "get_settings", lambda: _settings(AppEnvironment.DEVELOPMENT))
    monkeypatch.setattr("sys.argv", ["seed_demo_analytics.py"])

    with pytest.raises(SystemExit):
        _seed_module.main()
