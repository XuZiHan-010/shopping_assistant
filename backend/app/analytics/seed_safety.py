"""演示数据重灌和场景种子的共同写入护栏。"""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.config import AppEnvironment, Settings

_LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})


def assert_local_database_url(database_url: str) -> None:
    try:
        hostname = urlparse(database_url).hostname
    except ValueError as error:
        raise RuntimeError("全量演示 Seed 只能连接本机数据库") from error
    if hostname is None or hostname.lower() not in _LOCAL_DATABASE_HOSTS:
        raise RuntimeError("全量演示 Seed 只能连接本机数据库")


def reject_production(settings: Settings) -> None:
    if settings.app_env is AppEnvironment.PRODUCTION:
        raise RuntimeError("生产环境禁止运行演示 Seed")
