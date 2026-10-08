"""N4 B 内部状态迁移可以在可丢弃测试库升降级。"""

from alembic import command
from sqlalchemy import create_engine, inspect

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
    finally:
        engine.dispose()

    command.downgrade(config, "20260927_0041")
    command.upgrade(config, "20260928_0044")
    command.upgrade(config, "head")
