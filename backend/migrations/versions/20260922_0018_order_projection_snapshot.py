"""M2 订单投影、价格快照与有预检的历史回填。

Revision ID: 20260922_0018
Revises: 20260922_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0018"
down_revision: str | Sequence[str] | None = "20260922_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(14, 2)
# 冻结迁移时的映射快照；不 import 会随运行时代码变化的领域模块。
_FROM_LEGACY_TABLE: dict[str, tuple[str, str, str | None]] = {
    "CREATED": ("PENDING", "NOT_SHIPPED", None),
    "PAID": ("PAID", "NOT_SHIPPED", None),
    "SHIPPED": ("PAID", "SHIPPED", None),
    "COMPLETED": ("PAID", "DELIVERED", None),
    "CANCELLED": ("CLOSED", "NOT_SHIPPED", "CUSTOMER_CANCEL"),
    "CLOSED": ("CLOSED", "NOT_SHIPPED", "TIMEOUT"),
}


def _case(index: int) -> str:
    clauses = " ".join(
        f"WHEN '{status}' THEN {'NULL' if values[index] is None else repr(values[index])}"
        for status, values in _FROM_LEGACY_TABLE.items()
    )
    return f"CASE order_status {clauses} END"


_LEGACY_CHECK = (
    "(order_status = 'CREATED' AND payment_status = 'PENDING' "
    "AND fulfillment_status = 'NOT_SHIPPED' AND close_reason IS NULL) OR "
    "(order_status = 'PAID' AND payment_status = 'PAID' "
    "AND fulfillment_status = 'NOT_SHIPPED' AND close_reason IS NULL) OR "
    "(order_status = 'SHIPPED' AND payment_status = 'PAID' "
    "AND fulfillment_status IN ('SHIPPED','IN_TRANSIT','OUT_FOR_DELIVERY') "
    "AND close_reason IS NULL) OR "
    "(order_status = 'COMPLETED' AND payment_status = 'PAID' "
    "AND fulfillment_status = 'DELIVERED' AND close_reason IS NULL) OR "
    "(order_status = 'CANCELLED' AND payment_status = 'CLOSED' "
    "AND fulfillment_status = 'NOT_SHIPPED' AND close_reason = 'CUSTOMER_CANCEL') OR "
    "(order_status = 'CLOSED' AND payment_status = 'CLOSED' "
    "AND fulfillment_status = 'NOT_SHIPPED' AND close_reason = 'TIMEOUT')"
)


def _precheck() -> None:
    connection = op.get_bind()
    failures = (
        connection.execute(
            sa.text("""
        SELECT order_no, 'paid_at' AS field FROM orders
        WHERE (order_status IN ('PAID','SHIPPED','COMPLETED') AND paid_at IS NULL)
           OR (order_status IN ('CREATED','CANCELLED','CLOSED') AND paid_at IS NOT NULL)
        UNION ALL
        SELECT o.order_no, 'item_amount / quantity' AS field
        FROM order_items i JOIN orders o ON o.id = i.order_id
        WHERE i.quantity <= 0 OR (
            i.quantity > 0 AND ROUND(i.item_amount / i.quantity, 2) * i.quantity <> i.item_amount
        )
    """)
        )
        .mappings()
        .all()
    )
    if failures:
        examples = ", ".join(f"{row['order_no']}({row['field']})" for row in failures[:10])
        # P0001；异常会回滚本迁移的全部 DDL。
        connection.execute(
            sa.text("SELECT set_config('n1.m2_precheck_error', :message, true)"),
            {"message": f"M2 legacy precheck failed: {len(failures)} rows: {examples}"},
        )
        connection.execute(
            sa.text(
                "DO $$ BEGIN RAISE EXCEPTION '%', current_setting('n1.m2_precheck_error'); END $$"
            )
        )


def upgrade() -> None:
    if not op.get_context().as_sql:
        _precheck()

    for name, type_ in (
        ("payment_status", sa.String(16)),
        ("fulfillment_status", sa.String(24)),
        ("after_sale_status", sa.String(16)),
        ("close_reason", sa.String(16)),
        ("lifecycle_origin", sa.String(16)),
    ):
        op.add_column("orders", sa.Column(name, type_, nullable=True))
    op.add_column(
        "orders",
        sa.Column("source_timezone", sa.String(64), nullable=False, server_default="Asia/Shanghai"),
    )
    for name in ("unit_price", "discount_amount", "line_total"):
        op.add_column("order_items", sa.Column(name, _MONEY, nullable=True))

    op.execute(f"""
        UPDATE orders SET
          payment_status = {_case(0)},
          fulfillment_status = {_case(1)},
          close_reason = {_case(2)},
          after_sale_status = 'NONE', lifecycle_origin = 'LEGACY_V1'
    """)
    op.execute("""
        UPDATE order_items SET unit_price = ROUND(item_amount / quantity, 2),
          discount_amount = 0, line_total = item_amount
    """)
    for name in ("payment_status", "fulfillment_status", "after_sale_status", "lifecycle_origin"):
        op.alter_column("orders", name, nullable=False)
    for name in ("unit_price", "discount_amount", "line_total"):
        op.alter_column("order_items", name, nullable=False)
    op.alter_column("orders", "after_sale_status", server_default="NONE")
    op.create_check_constraint(
        "ck_orders_payment_status", "orders", "payment_status IN ('PENDING','PAID','CLOSED')"
    )
    op.create_check_constraint(
        "ck_orders_fulfillment_status",
        "orders",
        "fulfillment_status IN "
        "('NOT_SHIPPED','SHIPPED','IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED')",
    )
    op.create_check_constraint(
        "ck_orders_unpaid_not_shipped",
        "orders",
        "payment_status <> 'PENDING' OR fulfillment_status = 'NOT_SHIPPED'",
    )
    op.create_check_constraint(
        "ck_orders_closed_reason",
        "orders",
        "(payment_status = 'CLOSED') = (close_reason IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_orders_lifecycle_origin", "orders", "lifecycle_origin IN ('LEGACY_V1','V2')"
    )
    op.create_check_constraint("ck_orders_legacy_status_consistent", "orders", _LEGACY_CHECK)
    op.create_check_constraint(
        "ck_order_items_nonnegative_amounts",
        "order_items",
        "discount_amount >= 0 AND line_total >= 0",
    )
    op.create_check_constraint(
        "ck_order_items_price_snapshot",
        "order_items",
        "line_total = unit_price * quantity - discount_amount",
    )
    op.create_check_constraint(
        "ck_order_items_legacy_amount_consistent", "order_items", "item_amount = line_total"
    )


def downgrade() -> None:
    for name in (
        "ck_order_items_legacy_amount_consistent",
        "ck_order_items_price_snapshot",
        "ck_order_items_nonnegative_amounts",
    ):
        op.drop_constraint(name, "order_items", type_="check")
    for name in (
        "ck_orders_legacy_status_consistent",
        "ck_orders_lifecycle_origin",
        "ck_orders_closed_reason",
        "ck_orders_unpaid_not_shipped",
        "ck_orders_fulfillment_status",
        "ck_orders_payment_status",
    ):
        op.drop_constraint(name, "orders", type_="check")
    for name in ("line_total", "discount_amount", "unit_price"):
        op.drop_column("order_items", name)
    for name in (
        "source_timezone",
        "lifecycle_origin",
        "close_reason",
        "after_sale_status",
        "fulfillment_status",
        "payment_status",
    ):
        op.drop_column("orders", name)
