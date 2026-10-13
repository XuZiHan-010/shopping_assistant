"""记忆来源顺序、商家规范键与主体失效版本；不猜测合并历史偏好。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_0052"
down_revision: str | Sequence[str] | None = "20261004_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("merchants", "customer_memory_preferences", "memory_extraction_jobs"):
        op.add_column(
            table,
            sa.Column(
                "memory_generation", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
        )
    for table in ("customer_memories", "merchant_memory_facts"):
        op.add_column(
            table,
            sa.Column("source_order", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        )
    op.add_column("merchant_memory_facts", sa.Column("key", sa.String(100), nullable=True))
    op.add_column(
        "memory_extraction_jobs",
        sa.Column("source_order", sa.BigInteger(), sa.Identity(), nullable=False),
    )
    # 旧任务按已保存的来源消息时间排序；新任务在主体锁下分配序号。
    op.execute("""
        WITH ranked AS (
            SELECT j.id, row_number() OVER (ORDER BY m.created_at, j.created_at, j.id) AS n
            FROM memory_extraction_jobs j JOIN messages m ON m.id = j.message_id
        )
        UPDATE memory_extraction_jobs j SET source_order = ranked.n
        FROM ranked WHERE ranked.id = j.id
    """)
    op.execute("""
        SELECT setval(pg_get_serial_sequence('memory_extraction_jobs', 'source_order'),
            COALESCE((SELECT max(source_order) FROM memory_extraction_jobs), 1),
            EXISTS(SELECT 1 FROM memory_extraction_jobs))
    """)
    op.create_unique_constraint(
        "uq_memory_extraction_jobs_source_order", "memory_extraction_jobs", ["source_order"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_memory_extraction_jobs_source_order", "memory_extraction_jobs", type_="unique"
    )
    op.drop_column("memory_extraction_jobs", "source_order")
    op.drop_column("merchant_memory_facts", "key")
    for table in ("customer_memories", "merchant_memory_facts"):
        op.drop_column(table, "source_order")
    for table in ("merchants", "customer_memory_preferences", "memory_extraction_jobs"):
        op.drop_column(table, "memory_generation")
