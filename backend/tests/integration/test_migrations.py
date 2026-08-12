import os
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

from alembic import command
from pytest import MonkeyPatch
from sqlalchemy import create_engine, inspect

from app.core.config import Settings
from tests.postgres import DEFAULT_TEST_DATABASE_URL, alembic_config, assert_test_database

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def test_migration_settings_honors_test_database_url(monkeypatch: MonkeyPatch) -> None:
    """防止迁移测试绕开集成门禁注入的独立测试库。"""

    injected_url = (
        "postgresql+psycopg://borough:borough_local@127.0.0.1:55442/borough_integrate_test"
    )
    monkeypatch.setenv("TEST_DATABASE_URL", injected_url)
    spec = spec_from_file_location("migration_settings_probe", Path(__file__))
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.migration_settings().database_url == injected_url


def migration_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=DATABASE_URL,
        frontend_origin="http://localhost:5173",
    )


def test_first_migration_renders_postgresql_sql_offline() -> None:
    output = StringIO()
    config = alembic_config(migration_settings().database_url)
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE merchants" in sql
    assert "CREATE TABLE audit_logs" in sql
    assert "CREATE TABLE llm_usage" in sql
    assert "CREATE TABLE users" not in sql
    assert "CREATE TABLE attachments" not in sql


def test_first_migration_upgrades_empty_postgres_and_can_repeat(
    postgres_url: str,
) -> None:
    assert_test_database(postgres_url)
    config = alembic_config(postgres_url)

    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(postgres_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {
        "merchants",
        "conversations",
        "messages",
        "answers",
        "feedback",
        "export_files",
        "metric_definitions",
        "knowledge_documents",
        "audit_logs",
        "llm_usage",
        # B4 的六张经营数据表：单独钉住，不能只靠其他集成测试间接覆盖——
        # 那些测试假定表已存在，迁移本身漏建表时它们只会报无关的连接错误，
        # 而不是清楚地指向「迁移没建对表」。
        "orders",
        "order_items",
        "products",
        "refunds",
        "returns",
        "support_tickets",
        "alembic_version",
    } <= table_names
    assert "users" not in table_names
    assert "attachments" not in table_names

    command.downgrade(config, "base")
    command.upgrade(config, "head")
