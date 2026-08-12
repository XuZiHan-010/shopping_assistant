"""创建 P0 演示经营数据表：商品、订单、订单明细、退款、退货、工单。

Revision ID: 20260804_0005
Revises: 20260804_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260804_0005"
down_revision: str | Sequence[str] | None = "20260804_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(precision=14, scale=2)


def _timestamps(*, updated: bool = False) -> list[sa.Column]:
    columns = [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        )
    ]
    if updated:
        columns.append(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
    return columns


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("product_code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("price", _MONEY, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("listed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(updated=True),
        sa.CheckConstraint(
            "status IN ('ONLINE', 'OFFLINE', 'AUDITING', 'REJECTED')",
            name="ck_products_status",
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "product_code", name="uq_products_merchant_code"),
    )
    op.create_index(
        "ix_products_merchant_business_date",
        "products",
        ["merchant_id", "business_date"],
    )
    op.create_index(
        "ix_products_merchant_category",
        "products",
        ["merchant_id", "category"],
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("order_no", sa.String(length=64), nullable=False),
        sa.Column("buyer_key", sa.String(length=64), nullable=False),
        sa.Column("order_status", sa.String(length=16), nullable=False),
        sa.Column("total_amount", _MONEY, nullable=False),
        sa.Column("paid_amount", _MONEY, nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(updated=True),
        sa.CheckConstraint(
            "order_status IN ('CREATED', 'PAID', 'SHIPPED', 'COMPLETED', 'CANCELLED', 'CLOSED')",
            name="ck_orders_status",
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "order_no", name="uq_orders_merchant_no"),
    )
    op.create_index(
        "ix_orders_merchant_business_date",
        "orders",
        ["merchant_id", "business_date"],
    )
    op.create_index(
        "ix_orders_merchant_status",
        "orders",
        ["merchant_id", "order_status"],
    )

    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("item_amount", _MONEY, nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_order_items_merchant_business_date",
        "order_items",
        ["merchant_id", "business_date"],
    )
    op.create_index("ix_order_items_order", "order_items", ["order_id"])

    op.create_table(
        "refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refund_amount", _MONEY, nullable=False),
        sa.Column("refund_reason", sa.String(length=64), nullable=False),
        sa.Column("refund_status", sa.String(length=16), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "refund_status IN ('PENDING', 'APPROVED', 'REJECTED', 'REFUNDED')",
            name="ck_refunds_status",
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_refunds_merchant_business_date",
        "refunds",
        ["merchant_id", "business_date"],
    )
    op.create_index("ix_refunds_order_item", "refunds", ["order_item_id"])

    op.create_table(
        "returns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("return_quantity", sa.Integer(), nullable=False),
        sa.Column("return_reason", sa.String(length=64), nullable=False),
        sa.Column("return_status", sa.String(length=16), nullable=False),
        sa.Column("logistics_status", sa.String(length=16), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "return_status IN ('REQUESTED', 'APPROVED', 'REJECTED', 'RECEIVED', 'COMPLETED')",
            name="ck_returns_status",
        ),
        sa.CheckConstraint(
            "logistics_status IN ('PENDING', 'SHIPPED', 'DELIVERED', 'LOST')",
            name="ck_returns_logistics_status",
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_item_id"], ["order_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_returns_merchant_business_date",
        "returns",
        ["merchant_id", "business_date"],
    )
    op.create_index("ix_returns_order_item", "returns", ["order_item_id"])

    op.create_table(
        "support_tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("ticket_no", sa.String(length=64), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ticket_status", sa.String(length=16), nullable=False),
        sa.Column("ticket_reason", sa.String(length=64), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(updated=True),
        sa.CheckConstraint(
            "ticket_status IN ('OPEN', 'PENDING', 'RESOLVED', 'CLOSED')",
            name="ck_support_tickets_status",
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "ticket_no", name="uq_support_tickets_merchant_no"),
    )
    op.create_index(
        "ix_support_tickets_merchant_business_date",
        "support_tickets",
        ["merchant_id", "business_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_support_tickets_merchant_business_date",
        table_name="support_tickets",
    )
    op.drop_table("support_tickets")

    op.drop_index("ix_returns_order_item", table_name="returns")
    op.drop_index("ix_returns_merchant_business_date", table_name="returns")
    op.drop_table("returns")

    op.drop_index("ix_refunds_order_item", table_name="refunds")
    op.drop_index("ix_refunds_merchant_business_date", table_name="refunds")
    op.drop_table("refunds")

    op.drop_index("ix_order_items_order", table_name="order_items")
    op.drop_index("ix_order_items_merchant_business_date", table_name="order_items")
    op.drop_table("order_items")

    op.drop_index("ix_orders_merchant_status", table_name="orders")
    op.drop_index("ix_orders_merchant_business_date", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_products_merchant_category", table_name="products")
    op.drop_index("ix_products_merchant_business_date", table_name="products")
    op.drop_table("products")
