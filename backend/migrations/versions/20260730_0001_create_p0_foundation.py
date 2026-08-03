"""创建 P0 商家、会话、知识与运维基础表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps(*, updated: bool = False) -> list[sa.Column]:
    columns = [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        )
    ]
    if updated:
        columns.append(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
    return columns


def upgrade() -> None:
    op.create_table(
        "merchants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("is_demo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        *_timestamps(updated=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED')",
            name="ck_merchants_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_code"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        *_timestamps(updated=True),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversations_merchant_created",
        "conversations",
        ["merchant_id", "created_at"],
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "role IN ('USER', 'ASSISTANT', 'SYSTEM')",
            name="ck_messages_role",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "ix_messages_merchant_created",
        "messages",
        ["merchant_id", "created_at"],
    )

    op.create_table(
        "answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_request_id", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(length=32),
            server_default=sa.text("'PROCESSING'"),
            nullable=False,
        ),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(updated=True),
        sa.CheckConstraint(
            "processing_status IN ('PROCESSING', 'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED_FINAL')",
            name="ck_answers_processing_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "merchant_id",
            "client_request_id",
            name="uq_answers_merchant_client_request",
        ),
    )
    op.create_index(
        "ix_answers_conversation_created",
        "answers",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_adopted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("reaction", sa.String(length=16), nullable=True),
        *_timestamps(updated=True),
        sa.CheckConstraint(
            "reaction IS NULL OR reaction IN ('LIKE', 'DISLIKE')",
            name="ck_feedback_reaction",
        ),
        sa.ForeignKeyConstraint(["answer_id"], ["answers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "merchant_id",
            "answer_id",
            name="uq_feedback_merchant_answer",
        ),
    )

    op.create_table(
        "metric_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("business_definition", sa.Text(), nullable=False),
        sa.Column("sql_definition", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        *_timestamps(updated=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DEPRECATED', 'UNVERIFIED')",
            name="ck_metric_definitions_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("metric_code"),
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'ACTIVE'"),
            nullable=False,
        ),
        *_timestamps(updated=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_knowledge_documents_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_documents_category_status",
        "knowledge_documents",
        ["category", "status"],
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_logs_merchant_created",
        "audit_logs",
        ["merchant_id", "created_at"],
    )

    op.create_table(
        "llm_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("call_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_usage_date", "llm_usage", ["usage_date"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_usage_date", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index("ix_audit_logs_merchant_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index(
        "ix_knowledge_documents_category_status",
        table_name="knowledge_documents",
    )
    op.drop_table("knowledge_documents")
    op.drop_table("metric_definitions")
    op.drop_table("feedback")
    op.drop_index("ix_answers_conversation_created", table_name="answers")
    op.drop_table("answers")
    op.drop_index("ix_messages_merchant_created", table_name="messages")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_merchant_created", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("merchants")
