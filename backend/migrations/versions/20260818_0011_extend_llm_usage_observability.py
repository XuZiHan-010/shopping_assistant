"""Extend LLM usage observability with reservation and failure details.

Revision ID: 20260818_0011
Revises: 20260813_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0011"
down_revision: str | Sequence[str] | None = "20260813_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_usage", sa.Column("failure_kind", sa.String(length=32), nullable=True))
    op.add_column(
        "llm_usage",
        sa.Column("reserved_tokens", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "llm_usage",
        sa.Column("usage_known", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(
        sa.text(
            "UPDATE llm_usage SET usage_known = CASE "
            "WHEN status IN ('SUCCEEDED', 'BUDGET_REJECTED') THEN true ELSE false END, "
            "reserved_tokens = CASE WHEN status = 'FAILED' THEN total_tokens ELSE 0 END"
        )
    )
    op.create_check_constraint(
        "ck_llm_usage_reserved_tokens_nonnegative",
        "llm_usage",
        "reserved_tokens >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_usage_reserved_tokens_nonnegative", "llm_usage", type_="check")
    op.drop_column("llm_usage", "usage_known")
    op.drop_column("llm_usage", "reserved_tokens")
    op.drop_column("llm_usage", "failure_kind")
