"""N2 模块 D：v2 Chat 回答落 `answers` 表。

此前 v2 回答的 `id` 现场生成、不落库，而反馈表 `feedback.answer_id` 外键指向 `answers.id`，
商家对任何 v2 回答提交反馈都只能得到 403；Chat BI 与质量回路也看不到 v2 流量。

- `answers.surface`：`SHOP` / `MERCHANT` 标记 v2 回答，v1 行为空；
- `uq_answers_merchant_client_request` 由整表唯一约束改为**只约束 v1 行**的部分唯一索引。
  v2 的幂等由 `idempotency_records` 按主体五元组裁决（契约 §8.7.3），同店不同顾客可以复用
  同一个 `client_request_id`；v1 行的唯一性与并发裁决不变。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0034"
down_revision: str | Sequence[str] | None = "20260923_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("surface", sa.String(16), nullable=True))
    op.create_check_constraint(
        "ck_answers_surface",
        "answers",
        "surface IS NULL OR surface IN ('SHOP','MERCHANT')",
    )
    op.drop_constraint("uq_answers_merchant_client_request", "answers", type_="unique")
    op.create_index(
        "uq_answers_merchant_client_request",
        "answers",
        ["merchant_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("surface IS NULL"),
    )


def downgrade() -> None:
    # v2 行会与 v1 唯一约束冲突；降级即放弃 v2 回答记录（反馈随外键级联删除）。
    op.execute("DELETE FROM answers WHERE surface IS NOT NULL")
    op.drop_index("uq_answers_merchant_client_request", "answers")
    op.create_unique_constraint(
        "uq_answers_merchant_client_request", "answers", ["merchant_id", "client_request_id"]
    )
    op.drop_constraint("ck_answers_surface", "answers", type_="check")
    op.drop_column("answers", "surface")
