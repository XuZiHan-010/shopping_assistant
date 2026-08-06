"""Create atomic daily LLM budget table.

Revision ID: 20260805_0008
Revises: 20260805_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260805_0008"
down_revision: str | Sequence[str] | None = "20260805_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_daily_budget",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("consumed_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("call_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usage_date", name="uq_llm_daily_budget_usage_date"),
    )


def downgrade() -> None:
    op.drop_table("llm_daily_budget")
