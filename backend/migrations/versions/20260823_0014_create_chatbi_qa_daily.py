"""Create the Chat BI daily rollup table.

Revision ID: 20260823_0014
Revises: 20260823_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0014"
down_revision: str | Sequence[str] | None = "20260823_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COUNTER_COLUMNS = (
    "answer_total",
    "adopted_count",
    "like_count",
    "dislike_count",
    "first_pass_count",
    "business_question_total",
    "hit_count",
    "degraded_count",
    "thinking_sample_count",
)


def upgrade() -> None:
    op.create_table(
        "chatbi_qa_daily",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        *(
            sa.Column(name, sa.Integer(), server_default=sa.text("0"), nullable=False)
            for name in _COUNTER_COLUMNS
        ),
        sa.Column("thinking_ms_sum", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stat_date", "merchant_id", "category", name="uq_chatbi_qa_daily_grain"
        ),
        *(
            sa.CheckConstraint(f"{name} >= 0", name=f"ck_chatbi_qa_daily_{name}_nonnegative")
            for name in _COUNTER_COLUMNS
        ),
        sa.CheckConstraint(
            "thinking_ms_sum >= 0", name="ck_chatbi_qa_daily_thinking_ms_sum_nonnegative"
        ),
    )
    op.create_index("ix_chatbi_qa_daily_stat_date", "chatbi_qa_daily", ["stat_date"])


def downgrade() -> None:
    op.drop_index("ix_chatbi_qa_daily_stat_date", table_name="chatbi_qa_daily")
    op.drop_table("chatbi_qa_daily")
