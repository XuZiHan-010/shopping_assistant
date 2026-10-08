"""M7：售后状态机主记录及旧售后表的可空关联。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0023"
down_revision: str | Sequence[str] | None = "20260922_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    money = sa.Numeric(14, 2)
    op.create_table(
        "after_sales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("buyer_key", sa.String(64), nullable=False),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("after_sale_type", sa.String(24), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("refund_amount", money, nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "after_sale_type IN ('RETURN_REFUND','REFUND_ONLY','TICKET')",
            name="ck_after_sales_type",
        ),
        sa.CheckConstraint(
            "state IN ('PENDING_MERCHANT','APPROVED','REJECTED','AWAITING_RETURN',"
            "'RECEIVED','REFUNDED','AWAITING_CUSTOMER_INFO','CLOSED')",
            name="ck_after_sales_state",
        ),
        sa.CheckConstraint("refund_amount >= 0", name="ck_after_sales_refund_amount"),
        sa.CheckConstraint("state_version >= 1", name="ck_after_sales_state_version"),
    )
    op.create_index("ix_after_sales_merchant_buyer", "after_sales", ["merchant_id", "buyer_key"])
    op.create_index("ix_after_sales_merchant_order", "after_sales", ["merchant_id", "order_id"])
    op.create_table(
        "after_sale_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "after_sale_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("after_sales.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("order_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("refund_amount", money, nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_after_sale_lines_quantity"),
        sa.CheckConstraint("refund_amount >= 0", name="ck_after_sale_lines_refund_amount"),
        sa.UniqueConstraint("after_sale_id", "order_item_id", name="uq_after_sale_lines_sale_item"),
    )
    for table in ("refunds", "returns", "support_tickets"):
        op.add_column(
            table, sa.Column("after_sale_id", postgresql.UUID(as_uuid=True), nullable=True)
        )
        op.create_foreign_key(
            f"fk_{table}_after_sale_id",
            table,
            "after_sales",
            ["after_sale_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_unique_constraint(
        "uq_support_tickets_after_sale_id", "support_tickets", ["after_sale_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_support_tickets_after_sale_id", "support_tickets", type_="unique")
    for table in ("support_tickets", "returns", "refunds"):
        op.drop_constraint(f"fk_{table}_after_sale_id", table, type_="foreignkey")
        op.drop_column(table, "after_sale_id")
    op.drop_table("after_sale_lines")
    op.drop_index("ix_after_sales_merchant_order", table_name="after_sales")
    op.drop_index("ix_after_sales_merchant_buyer", table_name="after_sales")
    op.drop_table("after_sales")
