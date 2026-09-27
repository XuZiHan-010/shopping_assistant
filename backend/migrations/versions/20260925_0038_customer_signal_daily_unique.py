"""N3 B：同店、同类、同商品、同日只保留一条派生信号。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0038"
down_revision: str | Sequence[str] | None = "20260925_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_customer_signals_daily_product", "customer_signals",
        ["merchant_id", "kind", "product_id", "signal_date"],
        unique=True, postgresql_where=sa.text("product_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_customer_signals_daily_product", table_name="customer_signals")
