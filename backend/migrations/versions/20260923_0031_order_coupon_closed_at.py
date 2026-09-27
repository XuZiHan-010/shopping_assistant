"""N2 模块 B Task 3：订单补 `coupon_id`、`closed_at`，订单行补 `title_snapshot`（契约 §8.10.1）。

`title_snapshot` 是价格快照的一部分：商品改名后，历史订单仍显示下单时的名称。

两列都可空：历史订单没有券也没有关闭时刻，v2 详情对历史订单一律 403，不需要回填。
`closed_at` 与 `payment_status = 'CLOSED'` 的成对关系只对 v2 订单成立，因此不加 CHECK，
由支付 / 关闭服务在同一条条件更新里一起写入。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0031"
down_revision: str | Sequence[str] | None = "20260923_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "coupon_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("coupons.id", ondelete="RESTRICT", name="fk_orders_coupon_id"),
            nullable=True,
        ),
    )
    op.add_column("orders", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("order_items", sa.Column("title_snapshot", sa.String(200), nullable=True))
    # 超时关闭任务按「待支付 + 下单时刻」扫描；只索引 v2 待支付订单，历史行不进索引。
    op.create_index(
        "ix_orders_v2_pending_placed_at",
        "orders",
        ["placed_at"],
        postgresql_where=sa.text("payment_status = 'PENDING' AND lifecycle_origin = 'V2'"),
    )


def downgrade() -> None:
    op.drop_index("ix_orders_v2_pending_placed_at", "orders")
    op.drop_column("order_items", "title_snapshot")
    op.drop_column("orders", "closed_at")
    op.drop_column("orders", "coupon_id")
