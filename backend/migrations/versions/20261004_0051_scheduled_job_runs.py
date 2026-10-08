"""N5 C Task 4：Cron 分发器的任务状态表 `scheduled_job_runs`（PRD §10.7）。

单一分发器每 5 分钟运行一次，靠这张表判断每个任务在当前时间片是否已经成功跑过；
失败不推进 `last_slot`，下一次调度在同一时间片重试。系统级调度状态，不含经营数据，
所以没有 `merchant_id`；`last_error` 只存异常类别。

Revision ID: 20261004_0051
Revises: 20261003_0050
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261004_0051"
down_revision: str | Sequence[str] | None = "20261003_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_job_runs",
        sa.Column("job_name", sa.String(64), primary_key=True),
        sa.Column("last_slot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=False),
        sa.Column("last_error", sa.String(120), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("run_count >= 0", name="ck_scheduled_job_runs_run_count"),
        sa.CheckConstraint(
            "last_status IN ('OK', 'FAILED')", name="ck_scheduled_job_runs_last_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("scheduled_job_runs")
