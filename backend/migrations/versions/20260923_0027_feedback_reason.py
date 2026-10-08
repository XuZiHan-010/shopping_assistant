"""N2 模块 D：给 v1 `feedback` 表补充可选的赞踩原因列，供 v2 反馈契约（§8.14.1）复用。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0027"
down_revision: str | Sequence[str] | None = "20260922_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("reason", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "reason")
