"""M1 商品内容与库存三元组。

Revision ID: 20260922_0017
Revises: 20260831_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0017"
down_revision: str | Sequence[str] | None = "20260831_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("short_description", sa.String(200)))
    op.add_column("products", sa.Column("detail_description", sa.Text()))
    op.add_column(
        "products",
        sa.Column(
            "attributes", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )
    op.add_column("products", sa.Column("image_url", sa.String(512)))
    op.add_column(
        "products", sa.Column("stock_on_hand", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "products", sa.Column("stock_reserved", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "products",
        sa.Column(
            "stock_available",
            sa.Integer(),
            sa.Computed("stock_on_hand - stock_reserved", persisted=True),
            nullable=False,
        ),
    )
    op.add_column("products", sa.Column("low_stock_threshold", sa.Integer()))
    op.add_column(
        "products", sa.Column("content_version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "products", sa.Column("source_locale", sa.String(8), nullable=False, server_default="zh-CN")
    )
    op.create_check_constraint("ck_products_stock_on_hand_nonneg", "products", "stock_on_hand >= 0")
    op.create_check_constraint(
        "ck_products_stock_reserved_nonneg", "products", "stock_reserved >= 0"
    )
    op.create_check_constraint(
        "ck_products_reserved_le_on_hand", "products", "stock_reserved <= stock_on_hand"
    )
    op.create_check_constraint(
        "ck_products_content_version_positive", "products", "content_version >= 1"
    )


def downgrade() -> None:
    for name in (
        "ck_products_content_version_positive",
        "ck_products_reserved_le_on_hand",
        "ck_products_stock_reserved_nonneg",
        "ck_products_stock_on_hand_nonneg",
    ):
        op.drop_constraint(name, "products", type_="check")
    for column in (
        "source_locale",
        "content_version",
        "low_stock_threshold",
        "stock_available",
        "stock_reserved",
        "stock_on_hand",
        "image_url",
        "attributes",
        "detail_description",
        "short_description",
    ):
        op.drop_column("products", column)
