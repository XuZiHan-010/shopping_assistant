from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.job_config import JobSettings


def _settings(**overrides: object) -> JobSettings:
    values: dict[str, object] = {"database_url": "postgresql+psycopg://user:pass@localhost/demo"}
    values.update(overrides)
    return JobSettings(**values)


def test_job_settings_needs_only_database_url() -> None:
    """Cron 任务不应因为 Web 服务的密钥缺失而起不来。"""

    settings = _settings()

    assert settings.database_url.endswith("/demo")
    assert settings.business_timezone == "Asia/Shanghai"


def test_job_settings_does_not_expose_web_service_secrets() -> None:
    """最小权限：任务配置里不得出现它用不到的密钥字段。"""

    field_names = set(JobSettings.model_fields)

    assert not field_names & {
        "llm_api_key",
        "admin_token",
        "export_signing_secret",
        "frontend_origin",
    }


def test_job_settings_rejects_non_shanghai_business_timezone() -> None:
    """与 Settings 同一口径：业务时区固定，避免汇总切日错位。"""

    with pytest.raises(ValidationError):
        _settings(business_timezone="UTC")


def test_job_settings_carries_database_retry_and_timeout_knobs() -> None:
    """Database 构造需要这四个字段，缺任何一个都会在运行期才炸。"""

    settings = _settings()

    assert settings.db_connect_max_attempts >= 1
    assert settings.db_connect_retry_seconds >= 0
    assert settings.db_statement_timeout_ms >= 100


def test_railway_postgres_url_uses_psycopg_driver() -> None:
    """与 Settings 同一口径：Railway 注入的 postgresql:// 必须补上 psycopg 驱动。

    不补的话 SQLAlchemy 会按无后缀的 URL 选中默认的 psycopg2 方言，而项目
    只装了 psycopg 3，Cron 一启动就 ModuleNotFoundError。Web 服务不受影响，
    因为它走 Settings——这正是这个缺口能漏到线上的原因。
    """

    settings = _settings(database_url="postgresql://user:pass@localhost/db")

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost/db"


def test_already_qualified_database_url_is_left_alone() -> None:
    """已带驱动后缀的 URL 不得被二次改写。"""

    settings = _settings(database_url="postgresql+psycopg://user:pass@localhost/db")

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost/db"
