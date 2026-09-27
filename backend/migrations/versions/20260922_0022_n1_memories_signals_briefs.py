"""M6：顾客记忆、商家记忆两层、顾客信号和当日简报。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0022"
down_revision: str | Sequence[str] | None = "20260922_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True)


def _merchant_id() -> sa.Column:
    return sa.Column(
        "merchant_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )


def upgrade() -> None:
    op.create_table(
        "customer_memories",
        _id(),
        _merchant_id(),
        sa.Column("buyer_key", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(2000), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "merchant_id", "buyer_key", "key", name="uq_customer_memories_owner_key"
        ),
    )
    op.create_table(
        "merchant_memory_facts",
        _id(),
        _merchant_id(),
        sa.Column("content", sa.String(4000), nullable=False),
        sa.Column("source_ref", sa.String(256), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        _created_at(),
    )
    op.create_index("ix_merchant_memory_facts_merchant", "merchant_memory_facts", ["merchant_id"])
    op.create_table(
        "merchant_memory_summaries",
        _id(),
        _merchant_id(),
        sa.Column("content", sa.String(4000), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("rebuilt_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
    )
    op.create_index(
        "ix_merchant_memory_summaries_merchant", "merchant_memory_summaries", ["merchant_id"]
    )
    op.create_table(
        "customer_signals",
        _id(),
        _merchant_id(),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("product_name", sa.String(200), nullable=True),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("derived_from", postgresql.JSONB(), nullable=False),
        sa.Column("is_ignored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ignore_reason", sa.String(500), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "kind IN ('RETURN_REQUESTS','REFUND_REQUESTS','SUPPORT_TICKETS','CONTENT_GAP')",
            name="ck_customer_signals_kind",
        ),
        sa.CheckConstraint("count > 0", name="ck_customer_signals_count"),
    )
    op.create_index(
        "ix_customer_signals_merchant_date", "customer_signals", ["merchant_id", "signal_date"]
    )
    op.create_table(
        "daily_briefs",
        _id(),
        _merchant_id(),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("brief_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_id", "business_date", name="uq_daily_briefs_merchant_date"),
    )


def downgrade() -> None:
    op.drop_table("daily_briefs")
    op.drop_index("ix_customer_signals_merchant_date", table_name="customer_signals")
    op.drop_table("customer_signals")
    op.drop_index("ix_merchant_memory_summaries_merchant", table_name="merchant_memory_summaries")
    op.drop_table("merchant_memory_summaries")
    op.drop_index("ix_merchant_memory_facts_merchant", table_name="merchant_memory_facts")
    op.drop_table("merchant_memory_facts")
    op.drop_table("customer_memories")
