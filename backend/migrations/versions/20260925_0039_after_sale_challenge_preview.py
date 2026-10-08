"""N3 B：保存售后界面确认时预览的对话摘要。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260925_0039"
down_revision: str | Sequence[str] | None = "20260925_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "after_sale_challenge_previews",
        sa.Column("nonce", sa.String(64), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("buyer_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("text", sa.String(2000)),
        sa.Column("unavailable_reason", sa.String(200)),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("after_sale_challenge_previews")
