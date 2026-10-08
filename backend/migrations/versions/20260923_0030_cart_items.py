"""N2 模块 B Task 2：顾客购物车（PRD C3，契约 §8.10）。

主体二选一：已绑定顾客按 `(merchant_id, buyer_key)`，访客按内部会话记录 ID。
两个部分唯一索引让「设置绝对数量」可以用 upsert 实现天然幂等。
购物车不占库存，因此表里没有任何库存或价格快照列。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0030"
down_revision: str | Sequence[str] | None = "20260923_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cart_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("buyer_key", sa.String(64), nullable=True),
        sa.Column(
            "guest_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("quantity BETWEEN 1 AND 99", name="ck_cart_items_quantity"),
        sa.CheckConstraint(
            "(buyer_key IS NULL) <> (guest_session_id IS NULL)", name="ck_cart_items_single_owner"
        ),
    )
    op.create_index(
        "uq_cart_items_buyer_product",
        "cart_items",
        ["merchant_id", "buyer_key", "product_id"],
        unique=True,
        postgresql_where=sa.text("buyer_key IS NOT NULL"),
    )
    op.create_index(
        "uq_cart_items_guest_product",
        "cart_items",
        ["guest_session_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("guest_session_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_cart_items_guest_product", "cart_items")
    op.drop_index("uq_cart_items_buyer_product", "cart_items")
    op.drop_table("cart_items")
