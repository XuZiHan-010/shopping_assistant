from app.db.base import Base

EXPECTED_FOUNDATION_TABLES = {
    "merchants",
    "conversations",
    "messages",
    "answers",
    "feedback",
    "metric_definitions",
    "knowledge_documents",
    "audit_logs",
    "llm_usage",
}


def test_metadata_contains_only_expected_b1_foundation_tables() -> None:
    table_names = set(Base.metadata.tables)

    assert table_names >= EXPECTED_FOUNDATION_TABLES
    assert "users" not in table_names
    assert "attachments" not in table_names


def test_all_foundation_tables_use_default_schema() -> None:
    assert all(table.schema is None for table in Base.metadata.tables.values())


def test_answers_enforce_merchant_scoped_idempotency_key() -> None:
    """v1 幂等键按商家唯一；v2 行（`surface` 非空）的幂等由 `idempotency_records` 裁决。"""

    answers = Base.metadata.tables["answers"]
    index = next(i for i in answers.indexes if i.name == "uq_answers_merchant_client_request")

    assert index.unique
    assert tuple(column.name for column in index.columns) == ("merchant_id", "client_request_id")
    assert str(index.dialect_options["postgresql"]["where"]) == "surface IS NULL"


def test_operations_tables_have_required_lookup_indexes() -> None:
    audit_indexes = {
        tuple(column.name for column in index.columns)
        for index in Base.metadata.tables["audit_logs"].indexes
    }
    usage_indexes = {
        tuple(column.name for column in index.columns)
        for index in Base.metadata.tables["llm_usage"].indexes
    }

    assert ("merchant_id", "created_at") in audit_indexes
    assert ("usage_date",) in usage_indexes
