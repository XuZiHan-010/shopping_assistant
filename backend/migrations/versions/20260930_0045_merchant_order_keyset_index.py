"""W 审查整改：商家订单按店铺及时间/ID 游标分页索引。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0045"
down_revision: str | Sequence[str] | None = "20260928_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_orders_v2_merchant_placed_id", "orders", ["merchant_id", "placed_at", "id"],
        postgresql_where=sa.text("lifecycle_origin = 'V2'"),
    )


def downgrade() -> None:
    op.drop_index("ix_orders_v2_merchant_placed_id", table_name="orders")
