import json
import os
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
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
        "machine_translation_cache",
        "resource_localizations",
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


# ---------------------------------------------------------------------------
# 20260831_0016：内容语言回填不得默认成 zh-CN
# ---------------------------------------------------------------------------

_CONTENT_LANGUAGE_SAMPLES = (
    ("english", "Gross merchandise value", "en-US"),
    ("mixed", "退款 GMV increased", "mixed"),
    ("und", "sku_001 https://example.com 123", "und"),
    ("zh", "这是一段完整的中文说明，用于介绍退款流程。", "zh-CN"),
)


def test_content_locale_migration_backfills_without_defaulting_to_zh_cn(
    postgres_url: str,
) -> None:
    """`0016` 必须用确定性分类回填历史行，四类样本（纯英文/中英混合/不可判定/
    纯中文）各自落到正确的 `source_locale`/`response_locale`，尤其是英文与
    混合样本不能被数据库默认值悄悄标成 `zh-CN`。"""

    config = alembic_config(postgres_url)
    command.downgrade(config, "20260831_0015")
    engine = create_engine(postgres_url)

    merchant_id = uuid4()
    conversation_id = uuid4()
    message_ids = {label: uuid4() for label, _, _ in _CONTENT_LANGUAGE_SAMPLES}
    answer_ids = {label: uuid4() for label, _, _ in _CONTENT_LANGUAGE_SAMPLES}
    document_ids = {label: uuid4() for label, _, _ in _CONTENT_LANGUAGE_SAMPLES}
    memory_ids = {label: uuid4() for label, _, _ in _CONTENT_LANGUAGE_SAMPLES}

    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM messages"))
            connection.execute(text("DELETE FROM answers"))
            connection.execute(text("DELETE FROM knowledge_documents"))
            connection.execute(text("DELETE FROM merchant_memories"))
            connection.execute(text("DELETE FROM conversations"))
            connection.execute(text("DELETE FROM merchants WHERE id = :id"), {"id": merchant_id})

            connection.execute(
                text(
                    "INSERT INTO merchants (id, merchant_code, display_name) "
                    "VALUES (:id, :merchant_code, :display_name)"
                ),
                {
                    "id": merchant_id,
                    "merchant_code": "content-locale-backfill-merchant",
                    "display_name": "内容语言回填商家",
                },
            )
            connection.execute(
                text("INSERT INTO conversations (id, merchant_id) VALUES (:id, :merchant_id)"),
                {"id": conversation_id, "merchant_id": merchant_id},
            )
            connection.execute(
                text(
                    "INSERT INTO messages (id, merchant_id, conversation_id, role, content) "
                    "VALUES (:id, :merchant_id, :conversation_id, 'USER', :content)"
                ),
                [
                    {
                        "id": message_ids[label],
                        "merchant_id": merchant_id,
                        "conversation_id": conversation_id,
                        "content": content,
                    }
                    for label, content, _ in _CONTENT_LANGUAGE_SAMPLES
                ],
            )
            connection.execute(
                text(
                    "INSERT INTO answers "
                    "(id, merchant_id, conversation_id, client_request_id, request_digest, "
                    "processing_status, response_payload) "
                    "VALUES (:id, :merchant_id, :conversation_id, :client_request_id, "
                    "'digest', 'SUCCEEDED', CAST(:response_payload AS jsonb))"
                ),
                [
                    {
                        "id": answer_ids[label],
                        "merchant_id": merchant_id,
                        "conversation_id": conversation_id,
                        "client_request_id": f"content-locale-{label}",
                        "response_payload": json.dumps({"answer": content}),
                    }
                    for label, content, _ in _CONTENT_LANGUAGE_SAMPLES
                ],
            )
            connection.execute(
                text(
                    "INSERT INTO knowledge_documents "
                    "(id, category, title, content, source, source_path) "
                    "VALUES (:id, 'GENERAL', '标题', :content, 'legacy', :source_path)"
                ),
                [
                    {
                        "id": document_ids[label],
                        "content": content,
                        "source_path": f"/legacy/content-locale-{label}",
                    }
                    for label, content, _ in _CONTENT_LANGUAGE_SAMPLES
                ],
            )
            connection.execute(
                text(
                    "INSERT INTO merchant_memories (id, merchant_id, category, content) "
                    "VALUES (:id, :merchant_id, :category, :content)"
                ),
                [
                    {
                        "id": memory_ids[label],
                        "merchant_id": merchant_id,
                        "category": f"CATEGORY_{label.upper()}",
                        "content": content,
                    }
                    for label, content, _ in _CONTENT_LANGUAGE_SAMPLES
                ],
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            message_locales = dict(
                connection.execute(
                    text("SELECT id, source_locale FROM messages WHERE id IN :ids").bindparams(
                        sa.bindparam("ids", expanding=True)
                    ),
                    {"ids": list(message_ids.values())},
                ).all()
            )
            answer_locales = dict(
                connection.execute(
                    text("SELECT id, response_locale FROM answers WHERE id IN :ids").bindparams(
                        sa.bindparam("ids", expanding=True)
                    ),
                    {"ids": list(answer_ids.values())},
                ).all()
            )
            document_locales = dict(
                connection.execute(
                    text(
                        "SELECT id, source_locale FROM knowledge_documents WHERE id IN :ids"
                    ).bindparams(sa.bindparam("ids", expanding=True)),
                    {"ids": list(document_ids.values())},
                ).all()
            )
            memory_locales = dict(
                connection.execute(
                    text(
                        "SELECT id, source_locale FROM merchant_memories WHERE id IN :ids"
                    ).bindparams(sa.bindparam("ids", expanding=True)),
                    {"ids": list(memory_ids.values())},
                ).all()
            )

        for label, _, expected in _CONTENT_LANGUAGE_SAMPLES:
            assert message_locales[message_ids[label]] == expected, label
            assert answer_locales[answer_ids[label]] == expected, label
            assert document_locales[document_ids[label]] == expected, label
            assert memory_locales[memory_ids[label]] == expected, label
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def test_content_locale_migration_upgrade_downgrade_round_trip(postgres_url: str) -> None:
    """`0016` 的列与 CHECK 约束能干净地升级、降级、再升级，不留残留对象。"""

    config = alembic_config(postgres_url)
    engine = create_engine(postgres_url)
    try:
        command.downgrade(config, "20260831_0015")
        columns = {column["name"] for column in inspect(engine).get_columns("messages")}
        assert "source_locale" not in columns

        command.upgrade(config, "head")
        columns = {column["name"] for column in inspect(engine).get_columns("messages")}
        assert "source_locale" in columns
    finally:
        command.upgrade(config, "head")
        engine.dispose()


# ---------------------------------------------------------------------------
# 20260831_0015：数据库层的作用域 CHECK 约束与按作用域拆分的唯一索引
# ---------------------------------------------------------------------------


def _insert_machine_translation_cache_row(
    connection: sa.engine.Connection,
    *,
    scope_kind: str,
    merchant_id: object,
    source_hash: str,
) -> None:
    connection.execute(
        text(
            "INSERT INTO machine_translation_cache "
            "(id, scope_kind, merchant_id, source_hash, source_language, target_locale, "
            "translated_text, model) "
            "VALUES (:id, :scope_kind, :merchant_id, :source_hash, 'zh-CN', 'en-US', "
            "'translated', 'fake')"
        ),
        {
            "id": uuid4(),
            "scope_kind": scope_kind,
            "merchant_id": merchant_id,
            "source_hash": source_hash,
        },
    )


def test_machine_translation_cache_check_rejects_merchant_scope_without_merchant_id(
    migrated_postgres: str,
) -> None:
    engine = create_engine(migrated_postgres)
    try:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_machine_translation_cache_row(
                connection, scope_kind="MERCHANT", merchant_id=None, source_hash="s" * 64
            )
    finally:
        engine.dispose()


def test_machine_translation_cache_check_rejects_global_scope_with_merchant_id(
    migrated_postgres: str, merchant_one_id_for_migration_test: object
) -> None:
    engine = create_engine(migrated_postgres)
    try:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_machine_translation_cache_row(
                connection,
                scope_kind="GLOBAL",
                merchant_id=merchant_one_id_for_migration_test,
                source_hash="t" * 64,
            )
    finally:
        engine.dispose()


@pytest.fixture
def merchant_one_id_for_migration_test(migrated_postgres: str) -> object:
    """本文件的原始 SQL 测试不经过 `db_session`/ORM 夹具，独立造一行商家记录。"""

    engine = create_engine(migrated_postgres)
    merchant_id = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO merchants (id, merchant_code, display_name) "
                    "VALUES (:id, :merchant_code, :display_name) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": merchant_id,
                    "merchant_code": f"migration-check-{merchant_id}",
                    "display_name": "迁移约束测试商家",
                },
            )
        return merchant_id
    finally:
        engine.dispose()


def test_machine_translation_cache_unique_index_isolates_by_merchant(
    migrated_postgres: str,
) -> None:
    """同一份 (源哈希, 源语言, 目标语言, prompt_version) 在两个不同商家的
    MERCHANT 作用域下必须能各存一份互不冲突；同一商家重复插入才应该撞唯一
    索引。"""

    engine = create_engine(migrated_postgres)
    merchant_a = uuid4()
    merchant_b = uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM machine_translation_cache"))
            for merchant_id, code in ((merchant_a, "a"), (merchant_b, "b")):
                connection.execute(
                    text(
                        "INSERT INTO merchants (id, merchant_code, display_name) "
                        "VALUES (:id, :merchant_code, :display_name)"
                    ),
                    {
                        "id": merchant_id,
                        "merchant_code": f"unique-index-merchant-{code}",
                        "display_name": f"唯一索引测试商家{code}",
                    },
                )

        with engine.begin() as connection:
            _insert_machine_translation_cache_row(
                connection, scope_kind="MERCHANT", merchant_id=merchant_a, source_hash="u" * 64
            )
            _insert_machine_translation_cache_row(
                connection, scope_kind="MERCHANT", merchant_id=merchant_b, source_hash="u" * 64
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_machine_translation_cache_row(
                connection, scope_kind="MERCHANT", merchant_id=merchant_a, source_hash="u" * 64
            )
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM machine_translation_cache"))
            connection.execute(
                text("DELETE FROM merchants WHERE id IN :ids").bindparams(
                    sa.bindparam("ids", expanding=True)
                ),
                {"ids": [merchant_a, merchant_b]},
            )
        engine.dispose()


def test_resource_localizations_unique_index_does_not_dedupe_by_source_hash(
    migrated_postgres: str,
) -> None:
    """两份不同资源即便原文（因此 `source_hash`）完全相同，人工译文也必须
    分别落两行，不能被按纯文本哈希的唯一索引意外合并成一行。"""

    engine = create_engine(migrated_postgres)
    resource_a = uuid4()
    resource_b = uuid4()
    same_source_hash = "v" * 64
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM resource_localizations"))
            for resource_id in (resource_a, resource_b):
                connection.execute(
                    text(
                        "INSERT INTO resource_localizations "
                        "(id, scope_kind, merchant_id, resource_type, resource_id, field_name, "
                        "source_hash, source_version, source_language, target_locale, "
                        "translated_text) "
                        "VALUES (:id, 'GLOBAL', NULL, 'KNOWLEDGE_DOCUMENT', :resource_id, "
                        "'content', :source_hash, 1, 'zh-CN', 'en-US', 'translated')"
                    ),
                    {"id": uuid4(), "resource_id": resource_id, "source_hash": same_source_hash},
                )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO resource_localizations "
                    "(id, scope_kind, merchant_id, resource_type, resource_id, field_name, "
                    "source_hash, source_version, source_language, target_locale, translated_text) "
                    "VALUES (:id, 'GLOBAL', NULL, 'KNOWLEDGE_DOCUMENT', :resource_id, "
                    "'content', :source_hash, 1, 'zh-CN', 'en-US', 'duplicate')"
                ),
                {"id": uuid4(), "resource_id": resource_a, "source_hash": same_source_hash},
            )
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM resource_localizations"))
        engine.dispose()
