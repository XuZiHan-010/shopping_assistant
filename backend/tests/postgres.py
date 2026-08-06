"""真实 PostgreSQL 测试库的接入点。

夹具本身放在 `tests/conftest.py`，好让 `tests/api` 和 `tests/integration` 共用
同一套跳过语义；这里只放不依赖 pytest 夹具的纯函数和常量，避免父级 conftest
反向 import 子目录里的测试模块。
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

BACKEND_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_test"
)

TRUNCATE_ALL_TABLES = (
    "TRUNCATE TABLE support_tickets, returns, refunds, order_items, orders, products, "
    "export_files, audit_logs, feedback, answers, messages, "
    "conversations, llm_usage, llm_daily_budget, metric_definitions, "
    "knowledge_documents, merchants CASCADE"
)


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def assert_test_database(database_url: str) -> None:
    database_name = make_url(database_url).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("迁移测试只允许连接名称以 _test 结尾的数据库")


def database_is_reachable(database_url: str) -> bool:
    url = make_url(database_url)
    host = url.host or "127.0.0.1"
    port = url.port or 5432
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def integration_db_is_required() -> bool:
    """CI 中必须真的跑集成测试，不允许静默跳过。"""

    return os.environ.get("REQUIRE_INTEGRATION_DB", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
