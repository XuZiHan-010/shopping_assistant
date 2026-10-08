"""N3 B：商家回复在审批事务内送达到顾客售后详情。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260925_0040"
down_revision: str | Sequence[str] | None = "20260925_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "after_sale_replies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("after_sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.String(2000), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["after_sale_id"], ["after_sales.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_id"], ["drafts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("draft_id", name="uq_after_sale_replies_draft"),
    )
    op.create_index(
        "ix_after_sale_replies_sale_time", "after_sale_replies", ["after_sale_id", "sent_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_after_sale_replies_sale_time", table_name="after_sale_replies")
    op.drop_table("after_sale_replies")
