"""N4 B：记忆抽取 outbox、顾客开关与商家总结依赖。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260928_0042"
down_revision: str | Sequence[str] | None = "20260927_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "session_record_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.create_table(
        "memory_extraction_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("message_id", name="uq_memory_extraction_jobs_message"),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','DONE','FAILED')",
            name="ck_memory_extraction_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_memory_extraction_jobs_attempts"),
    )
    op.create_index(
        "ix_memory_extraction_jobs_claim", "memory_extraction_jobs", ["status", "lease_until"]
    )
    op.create_table(
        "customer_memory_preferences",
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("merchants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("buyer_key", sa.String(64), primary_key=True),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "merchant_memory_summaries",
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "merchant_memory_summaries",
        sa.Column(
            "source_fact_ids", postgresql.JSONB(), nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("merchant_memory_summaries", "source_fact_ids")
    op.drop_column("merchant_memory_summaries", "is_stale")
    op.drop_table("customer_memory_preferences")
    op.drop_index("ix_memory_extraction_jobs_claim", table_name="memory_extraction_jobs")
    op.drop_table("memory_extraction_jobs")
    op.drop_column("messages", "session_record_id")
