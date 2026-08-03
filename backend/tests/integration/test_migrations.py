from io import StringIO

from alembic import command
from sqlalchemy import create_engine, inspect

from app.core.config import Settings
from tests.postgres import DEFAULT_TEST_DATABASE_URL, alembic_config, assert_test_database


def migration_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=DEFAULT_TEST_DATABASE_URL,
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
        "metric_definitions",
        "knowledge_documents",
        "audit_logs",
        "llm_usage",
        "alembic_version",
    } <= table_names
    assert "users" not in table_names
    assert "attachments" not in table_names

    command.downgrade(config, "base")
    command.upgrade(config, "head")
