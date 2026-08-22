import os
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from pytest import MonkeyPatch
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from tests.postgres import DEFAULT_TEST_DATABASE_URL, alembic_config, assert_test_database

DATABASE_URL = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def test_migration_settings_honors_test_database_url(monkeypatch: MonkeyPatch) -> None:
    """迁移测试必须使用集成门禁指定的独立测试库。"""

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


def test_llm_usage_observability_migration_backfills_and_enforces_reservation(
    postgres_url: str,
) -> None:
    """新字段须正确回填，且数据库层拒绝负的预留 token。"""

    config = alembic_config(postgres_url)
    command.downgrade(config, "20260813_0010")
    engine = create_engine(postgres_url)
    records = [
        {"id": uuid4(), "request_id": "failed", "total_tokens": 40, "status": "FAILED"},
        {
            "id": uuid4(),
            "request_id": "succeeded",
            "total_tokens": 60,
            "status": "SUCCEEDED",
        },
        {
            "id": uuid4(),
            "request_id": "budget-rejected",
            "total_tokens": 0,
            "status": "BUDGET_REJECTED",
        },
    ]
    insert_sql = text(
        "INSERT INTO llm_usage "
        "(id, request_id, usage_date, model, total_tokens, status) "
        "VALUES (:id, :request_id, :usage_date, :model, :total_tokens, :status)"
    )

    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM llm_usage"))
            connection.execute(
                insert_sql,
                [
                    {
                        **record,
                        "usage_date": date(2026, 8, 18),
                        "model": "deepseek-v4-flash",
                    }
                    for record in records
                ],
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT request_id, reserved_tokens, usage_known, failure_kind "
                        "FROM llm_usage ORDER BY request_id"
                    )
                )
                .mappings()
                .all()
            )

        assert rows == [
            {
                "request_id": "budget-rejected",
                "reserved_tokens": 0,
                "usage_known": True,
                "failure_kind": None,
            },
            {
                "request_id": "failed",
                "reserved_tokens": 40,
                "usage_known": False,
                "failure_kind": None,
            },
            {
                "request_id": "succeeded",
                "reserved_tokens": 0,
                "usage_known": True,
                "failure_kind": None,
            },
        ]

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO llm_usage "
                    "(id, request_id, usage_date, model, status, reserved_tokens) "
                    "VALUES (:id, :request_id, :usage_date, :model, :status, :reserved_tokens)"
                ),
                {
                    "id": uuid4(),
                    "request_id": "negative-reservation",
                    "usage_date": date(2026, 8, 18),
                    "model": "deepseek-v4-flash",
                    "status": "FAILED",
                    "reserved_tokens": -1,
                },
            )
    finally:
        command.upgrade(config, "head")
        engine.dispose()
