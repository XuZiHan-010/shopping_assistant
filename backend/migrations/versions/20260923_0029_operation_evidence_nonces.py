"""N2 模块 C：界面操作证据的 nonce 消费表（契约 §8.7.9）。

为什么必须落库：进程内集合在多实例部署或一次重启之后就失效了，而"证据只能用一次"
在那之后会静默失效——审批界面的一次性批准变成可重放。本表是 §8.7.9 规定的写端点实现前置。

`purpose` 让售后确认（`customer-confirmation:v1`，N3）复用同一张表，不再另建一张。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0029"
down_revision: str | Sequence[str] | None = "20260923_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_evidence_nonces",
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("purpose", "nonce", name="pk_operation_evidence_nonces"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_operation_evidence_nonces_window"),
    )
    # 过期清理任务按到期时间扫；未消费的过期行由 Cron 删除（接线在 N5）。
    op.create_index(
        "ix_operation_evidence_nonces_expires_at",
        "operation_evidence_nonces",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operation_evidence_nonces_expires_at", "operation_evidence_nonces")
    op.drop_table("operation_evidence_nonces")
