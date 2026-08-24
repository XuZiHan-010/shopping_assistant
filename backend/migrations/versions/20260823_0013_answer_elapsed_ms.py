"""Add per-answer elapsed milliseconds for the Chat BI thinking-time metric.

Revision ID: 20260823_0013
Revises: 20260821_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0013"
down_revision: str | Sequence[str] | None = "20260821_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("elapsed_ms", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_answers_elapsed_ms_nonnegative",
        "answers",
        "elapsed_ms IS NULL OR elapsed_ms >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_answers_elapsed_ms_nonnegative", "answers", type_="check")
    op.drop_column("answers", "elapsed_ms")
