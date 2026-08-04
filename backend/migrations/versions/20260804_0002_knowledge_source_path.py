"""为团队知识保留来源路径与完整性标记。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0002"
down_revision: str | Sequence[str] | None = "20260730_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("source_path", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    # 既有行没有来源路径；先按 id 生成稳定路径，再建立唯一索引以避免冲突。
    op.execute("UPDATE knowledge_documents SET source_path = 'legacy/' || id::text")
    op.alter_column("knowledge_documents", "source_path", server_default=None)
    op.create_index(
        "uq_knowledge_documents_source_path",
        "knowledge_documents",
        ["source_path"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_knowledge_documents_source_path", table_name="knowledge_documents")
    op.drop_column("knowledge_documents", "is_complete")
    op.drop_column("knowledge_documents", "source_path")
