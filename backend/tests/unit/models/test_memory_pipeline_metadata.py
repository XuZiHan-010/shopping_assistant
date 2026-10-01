"""N4 B 记忆内部状态必须在 ORM 元数据中完整登记。"""

import app.models  # noqa: F401 - 注册所有 ORM 模型
from app.models.base import Base


def test_outbox_is_keyed_by_message_without_copied_identity() -> None:
    table = Base.metadata.tables["memory_extraction_jobs"]
    assert {"message_id", "status", "attempts", "lease_until", "last_error"} <= set(table.c.keys())
    assert "merchant_id" not in table.c
    assert "buyer_key" not in table.c
    assert any(
        constraint.name == "uq_memory_extraction_jobs_message" for constraint in table.constraints
    )
    assert any(
        foreign_key.target_fullname == "messages.id"
        for foreign_key in table.c.message_id.foreign_keys
    )


def test_customer_preference_uses_both_owner_keys() -> None:
    table = Base.metadata.tables["customer_memory_preferences"]
    assert {column.name for column in table.primary_key.columns} == {"merchant_id", "buyer_key"}
    assert table.c.memory_enabled.server_default is not None


def test_summary_records_staleness_and_source_facts() -> None:
    table = Base.metadata.tables["merchant_memory_summaries"]
    assert {"is_stale", "source_fact_ids"} <= set(table.c.keys())
    assert not table.c.is_stale.nullable
    assert not table.c.source_fact_ids.nullable


def test_message_keeps_trusted_session_reference_for_outbox_resolution() -> None:
    table = Base.metadata.tables["messages"]
    assert "session_record_id" in table.c
    assert any(
        key.target_fullname == "agent_sessions.id"
        for key in table.c.session_record_id.foreign_keys
    )


def test_merchant_fact_tombstone_supports_idempotent_delete() -> None:
    facts = Base.metadata.tables["merchant_memory_facts"]
    assert "deleted_at" in facts.c
    summaries = Base.metadata.tables["merchant_memory_summaries"]
    assert any(
        constraint.name == "uq_merchant_memory_summaries_category"
        for constraint in summaries.constraints
    )
