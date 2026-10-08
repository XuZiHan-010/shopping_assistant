"""N5 B：每日 LLM 预算按级别分行（全局 / 角色 / 店铺，PRD §10.2）。

`llm_daily_budget` 加 `scope_key`，唯一约束由 `(usage_date)` 改为 `(usage_date, scope_key)`。
历史行都是全局行，默认值 `GLOBAL` 让它们原样成为全局级，不需要回填。

降级会恢复「每天一行」：若库里已有非全局行，先删掉它们（它们只是当日计数，不是业务事实），
否则旧唯一约束无法建立。

Revision ID: 20261003_0049
Revises: 20261003_0048
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_0049"
down_revision: str | Sequence[str] | None = "20261003_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "llm_daily_budget"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("scope_key", sa.String(120), nullable=False, server_default=sa.text("'GLOBAL'")),
    )
    op.drop_constraint("uq_llm_daily_budget_usage_date", _TABLE, type_="unique")
    op.create_unique_constraint("uq_llm_daily_budget_scope", _TABLE, ["usage_date", "scope_key"])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM llm_daily_budget WHERE scope_key <> 'GLOBAL'"))
    op.drop_constraint("uq_llm_daily_budget_scope", _TABLE, type_="unique")
    op.create_unique_constraint("uq_llm_daily_budget_usage_date", _TABLE, ["usage_date"])
    op.drop_column(_TABLE, "scope_key")
