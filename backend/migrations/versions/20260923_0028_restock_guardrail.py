"""N2 模块 C：给护栏配置补充补货上限列。

M5 的护栏配置只覆盖价格与折扣；补货草稿（PRD M5、M10）同样要在应用时按「当时生效」的
配置复检，因此上限必须是按商家可改的数据，而不是代码常量——常量改不了，测试也就证明不了
「预检通过但应用前护栏收紧」这条路径。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0028"
down_revision: str | Sequence[str] | None = "20260923_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_MAX_RESTOCK_DELTA = 500


def upgrade() -> None:
    op.add_column(
        "guardrail_configs",
        sa.Column(
            "max_restock_delta",
            sa.Integer(),
            nullable=False,
            server_default=sa.text(str(DEFAULT_MAX_RESTOCK_DELTA)),
        ),
    )
    op.create_check_constraint(
        "ck_guardrail_configs_max_restock_delta",
        "guardrail_configs",
        "max_restock_delta > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_guardrail_configs_max_restock_delta", "guardrail_configs")
    op.drop_column("guardrail_configs", "max_restock_delta")
