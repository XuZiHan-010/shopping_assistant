"""N3 C：drafts.batch_id，支持商品内容批量起草的按批次勾选批准。

商品内容批量起草拆成"每个商品一份子草稿，共享一个 batch_id"，而不是一份草稿里塞多个商品——
后者会破坏"一份草稿一个版本"的状态机（部分批准无法表达）。`batch_id` 只在
`CONTENT_CHANGE` 草稿上非空，其余种类恒为 null（应用层约束见 `DraftSummary`）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260925_0037"
down_revision: str | Sequence[str] | None = "20260925_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drafts", sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_check_constraint(
        "ck_drafts_batch_id_only_content_change",
        "drafts",
        "(batch_id IS NULL) OR (kind = 'CONTENT_CHANGE')",
    )
    op.create_index(
        "ix_drafts_batch_id",
        "drafts",
        ["batch_id"],
        postgresql_where=sa.text("batch_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_drafts_batch_id", table_name="drafts")
    op.drop_constraint("ck_drafts_batch_id_only_content_change", "drafts", type_="check")
    op.drop_column("drafts", "batch_id")
