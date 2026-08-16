"""Add source dimensions for controlled generated metric queries.

Revision ID: 20260813_0010
Revises: 20260812_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0010"
down_revision: str | Sequence[str] | None = "20260812_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("spu_id", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("address_city_name", sa.String(length=64), nullable=True))
    op.execute(sa.text("UPDATE products SET spu_id = product_code WHERE spu_id IS NULL"))
    op.create_index(
        "ix_orders_merchant_address_city",
        "orders",
        ["merchant_id", "address_city_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_merchant_address_city", table_name="orders")
    op.drop_column("orders", "address_city_name")
    op.drop_column("products", "spu_id")
