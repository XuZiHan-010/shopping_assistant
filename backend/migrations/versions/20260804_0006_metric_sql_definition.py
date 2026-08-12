"""Refresh metric sql_definition with the B4 query contract.

Historical migrations must stay reproducible, so the new values are inlined
here instead of imported from ``app.metrics.seed``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0006"
down_revision: str | Sequence[str] | None = "20260804_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("gmv", "SUM(orders.paid_amount) WHERE order_status IN ('PAID','SHIPPED','COMPLETED')"),
    ("order_count", "COUNT(orders.id)"),
    ("paying_user_count", "COUNT(DISTINCT orders.buyer_key) WHERE paid_at IS NOT NULL"),
    ("successful_order_count", "COUNT(orders.id) WHERE order_status = 'COMPLETED'"),
    ("refund_count", "COUNT(refunds.id) WHERE refund_status IN ('APPROVED','REFUNDED')"),
    ("refund_amount", "SUM(refunds.refund_amount) WHERE refund_status = 'REFUNDED'"),
    ("return_count", "SUM(returns.return_quantity)"),
    ("return_rate", "SUM(returns.return_quantity) / NULLIF(SUM(order_items.quantity), 0)"),
    ("support_ticket_count", "COUNT(support_tickets.id)"),
)


def upgrade() -> None:
    for code, definition in _DEFINITIONS:
        op.execute(
            sa.text(
                "UPDATE metric_definitions SET sql_definition = :definition "
                "WHERE metric_code = :code"
            ).bindparams(definition=definition, code=code)
        )


def downgrade() -> None:
    for code, _ in _DEFINITIONS:
        op.execute(
            sa.text(
                "UPDATE metric_definitions SET sql_definition = :definition "
                "WHERE metric_code = :code"
            ).bindparams(definition=f"SUM({code})", code=code)
        )
