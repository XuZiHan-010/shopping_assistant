"""N4 B 内部状态迁移可以在可丢弃测试库升降级。"""

from alembic import command
from sqlalchemy import create_engine, inspect, text

from tests.postgres import alembic_config, assert_test_database


def test_memory_pipeline_migration_roundtrip(postgres_url: str) -> None:
    assert_test_database(postgres_url)
    config = alembic_config(postgres_url)
    command.upgrade(config, "20260927_0041")
    command.downgrade(config, "20260927_0041")
    command.upgrade(config, "20260928_0044")
    # ORM 对齐检查须在当前 head；N4 的历史迁移仍在上面单独升级验证。
    command.upgrade(config, "head")

    command.check(config)

    engine = create_engine(postgres_url)
    try:
        inspector = inspect(engine)
        assert {"memory_extraction_jobs", "customer_memory_preferences"} <= set(
            inspector.get_table_names()
        )
        assert {"is_stale", "source_fact_ids"} <= {
            column["name"] for column in inspector.get_columns("merchant_memory_summaries")
        }
        assert "session_record_id" in {
            column["name"] for column in inspector.get_columns("messages")
        }
        assert "deleted_at" in {
            column["name"] for column in inspector.get_columns("merchant_memory_facts")
        }
        assert {"key", "source_order"} <= {
            column["name"] for column in inspector.get_columns("merchant_memory_facts")
        }
        assert {"source_order", "memory_generation"} <= {
            column["name"] for column in inspector.get_columns("memory_extraction_jobs")
        }
    finally:
        engine.dispose()

    command.downgrade(config, "20260927_0041")
    command.upgrade(config, "20260928_0044")
    command.upgrade(config, "head")


def test_memory_upgrade_keeps_legacy_facts_and_orders_existing_jobs(postgres_url: str) -> None:
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    assert_test_database(postgres_url)
    config = alembic_config(postgres_url)
    command.upgrade(config, "head")
    command.downgrade(config, "20261004_0051")
    engine = create_engine(postgres_url)
    merchant, conversation, fact = uuid4(), uuid4(), uuid4()
    older, newer = uuid4(), uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO merchants(id, merchant_code, display_name) "
                    "VALUES(:id, :code, :name)"
                ),
                {"id": merchant, "code": f"memory-migration-{merchant}", "name": "Borough测试商家"},
            )
            connection.execute(
                text(
                    "INSERT INTO conversations(id, merchant_id, surface, conversation_kind) "
                    "VALUES(:id, :merchant, 'MERCHANT', 'CHAT')"
                ),
                {"id": conversation, "merchant": merchant},
            )
            for message, at in [
                (newer, datetime(2026, 10, 13, tzinfo=UTC)),
                (older, datetime(2026, 10, 13, tzinfo=UTC) - timedelta(days=1)),
            ]:
                connection.execute(
                    text(
                        "INSERT INTO messages(id, merchant_id, conversation_id, role, content, "
                        "source_locale, created_at) VALUES(:id, :merchant, :conversation, "
                        "'USER', '偏好', 'zh-CN', :at)"
                    ),
                    {"id": message, "merchant": merchant, "conversation": conversation, "at": at},
                )
                connection.execute(
                    text(
                        "INSERT INTO memory_extraction_jobs(id, message_id) VALUES(:id, :message)"
                    ),
                    {"id": uuid4(), "message": message},
                )
            connection.execute(
                text(
                    "INSERT INTO merchant_memory_facts"
                    "(id, merchant_id, category, content, source_ref) "
                    "VALUES(:id, :merchant, 'tone', '回复语气正式', :source)"
                ),
                {"id": fact, "merchant": merchant, "source": f"{conversation}:{older}"},
            )
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT content, key, source_order FROM merchant_memory_facts WHERE id=:id"),
                {"id": fact},
            ).one()
            assert tuple(row) == ("回复语气正式", None, 0)
            jobs = dict(
                connection.execute(
                    text(
                        "SELECT message_id, source_order FROM memory_extraction_jobs "
                        "WHERE message_id IN (:older, :newer)"
                    ),
                    {"older": older, "newer": newer},
                ).all()
            )
            assert 0 < jobs[older] < jobs[newer]
    finally:
        engine.dispose()
        command.upgrade(config, "head")
