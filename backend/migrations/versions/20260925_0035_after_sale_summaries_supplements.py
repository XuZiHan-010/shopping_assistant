"""N3 B：售后摘要不可变快照与顾客补充说明。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260925_0035"
down_revision: str | Sequence[str] | None = "20260923_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "after_sales",
        sa.Column(
            "conversation_summary_status", sa.String(16),
            nullable=False, server_default="NOT_SHARED",
        ),
    )
    op.add_column("after_sales", sa.Column("conversation_summary_text", sa.String(2000)))
    op.add_column("after_sales", sa.Column("conversation_summary_reason", sa.String(200)))
    op.create_check_constraint(
        "ck_after_sales_conversation_summary", "after_sales",
        "(conversation_summary_status = 'NOT_SHARED' "
        "AND conversation_summary_text IS NULL AND conversation_summary_reason IS NULL) OR "
        "(conversation_summary_status = 'AVAILABLE' "
        "AND conversation_summary_text IS NOT NULL AND conversation_summary_reason IS NULL) OR "
        "(conversation_summary_status = 'UNAVAILABLE' "
        "AND conversation_summary_text IS NULL AND conversation_summary_reason IS NOT NULL)",
    )
    op.create_table(
        "after_sale_supplements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("after_sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.String(1000), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["after_sale_id"], ["after_sales.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_after_sale_supplements_sale_time", "after_sale_supplements",
        ["after_sale_id", "submitted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_after_sale_supplements_sale_time", table_name="after_sale_supplements")
    op.drop_table("after_sale_supplements")
    op.drop_constraint("ck_after_sales_conversation_summary", "after_sales", type_="check")
    op.drop_column("after_sales", "conversation_summary_reason")
    op.drop_column("after_sales", "conversation_summary_text")
    op.drop_column("after_sales", "conversation_summary_status")
