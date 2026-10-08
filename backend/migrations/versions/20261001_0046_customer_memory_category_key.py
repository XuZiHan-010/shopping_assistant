"""N4-B 审查整改：顾客记忆唯一键加入 category。

原唯一键 `(merchant_id, buyer_key, key)` 让同名 key 的不同类别互相覆盖
（「偏好/颜色」被「偏好/尺码」静默替换）。改为 `(merchant_id, buyer_key, category, key)`：
同一类别下同一 key 仍是更新而非堆叠（PRD C7）。

降级会恢复旧约束：若库中已有「同一 key、不同类别」的多行，旧约束无法建立，降级会明确失败，
需先人工决定保留哪一行——这里不替用户删除记忆。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261001_0046"
down_revision: str | Sequence[str] | None = "20260930_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "customer_memories"
_CONSTRAINT = "uq_customer_memories_owner_key"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")
    op.create_unique_constraint(
        _CONSTRAINT, _TABLE, ["merchant_id", "buyer_key", "category", "key"]
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")
    op.create_unique_constraint(_CONSTRAINT, _TABLE, ["merchant_id", "buyer_key", "key"])
