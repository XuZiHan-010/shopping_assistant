"""Add traceable governance fields to metric definitions.

Revision ID: 20260812_0009
Revises: 20260805_0008
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0009"
down_revision: str | Sequence[str] | None = "20260805_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_METRIC_TRACEABILITY: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("gmv", ("date", "product", "category"), "orders"),
    ("order_count", ("date", "product", "category", "order_status"), "orders"),
    ("paying_user_count", ("date", "product", "category"), "orders"),
    ("successful_order_count", ("date", "product", "category", "order_status"), "orders"),
    ("refund_count", ("date", "refund_reason"), "refunds"),
    ("refund_amount", ("date", "refund_reason"), "refunds"),
    ("return_count", ("date", "return_reason", "return_status"), "returns"),
    ("return_rate", ("date", "product", "category"), "order_items"),
    ("support_ticket_count", ("date", "ticket_status"), "support_tickets"),
)


def upgrade() -> None:
    op.add_column("metric_definitions", sa.Column("dimensions", postgresql.JSONB(), nullable=True))
    op.add_column(
        "metric_definitions", sa.Column("source_database", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "metric_definitions", sa.Column("source_table", sa.String(length=64), nullable=True)
    )
    op.add_column("metric_definitions", sa.Column("report_url", sa.Text(), nullable=True))
    op.add_column("metric_definitions", sa.Column("generated", sa.Boolean(), nullable=True))
    op.add_column("metric_definitions", sa.Column("notice", sa.Text(), nullable=True))

    op.execute(sa.text("UPDATE metric_definitions SET source = 'METRIC_CATALOG'"))
    op.execute(sa.text("UPDATE metric_definitions SET generated = false, notice = NULL"))
    for code, dimensions, source_table in _METRIC_TRACEABILITY:
        op.execute(
            sa.text(
                "UPDATE metric_definitions "
                "SET dimensions = CAST(:dimensions AS jsonb), source_database = 'public', "
                "source_table = :source_table "
                "WHERE metric_code = :code"
            ).bindparams(dimensions=json.dumps(dimensions), source_table=source_table, code=code)
        )

    op.execute(
        sa.text(
            "UPDATE metric_definitions SET dimensions = '[]'::jsonb, "
            "source_database = 'public', source_table = '' "
            "WHERE dimensions IS NULL OR source_database IS NULL OR source_table IS NULL"
        )
    )
    op.alter_column("metric_definitions", "dimensions", nullable=False)
    op.alter_column("metric_definitions", "source_database", nullable=False)
    op.alter_column("metric_definitions", "source_table", nullable=False)
    op.alter_column("metric_definitions", "generated", nullable=False)


def downgrade() -> None:
    op.drop_column("metric_definitions", "notice")
    op.drop_column("metric_definitions", "generated")
    op.drop_column("metric_definitions", "report_url")
    op.drop_column("metric_definitions", "source_table")
    op.drop_column("metric_definitions", "source_database")
    op.drop_column("metric_definitions", "dimensions")
