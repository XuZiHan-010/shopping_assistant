"""N4 B：商家记忆删除幂等墓碑与每类唯一总结。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0043"
down_revision: str | Sequence[str] | None = "20260928_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "merchant_memory_facts",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_merchant_memory_summaries_category", "merchant_memory_summaries",
        ["merchant_id", "category"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_merchant_memory_summaries_category", "merchant_memory_summaries", type_="unique"
    )
    op.drop_column("merchant_memory_facts", "deleted_at")
