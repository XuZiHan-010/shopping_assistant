"""Add daily report system conversations and the ordering-user metric.

Revision ID: 20260821_0012
Revises: 20260820_0011
"""

import json
from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from app.metrics.seed import METRIC_SEED

revision: str = "20260821_0012"
down_revision: str | Sequence[str] | None = "20260820_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("conversation_kind", sa.String(length=32), server_default="CHAT", nullable=False),
    )
    op.create_check_constraint(
        "ck_conversations_kind",
        "conversations",
        "conversation_kind IN ('CHAT', 'DAILY_REPORT')",
    )
    op.create_index(
        "uq_conversations_merchant_daily_report",
        "conversations",
        ["merchant_id"],
        unique=True,
        postgresql_where=sa.text("conversation_kind = 'DAILY_REPORT'"),
    )

    item = next(seed for seed in METRIC_SEED if seed.metric_code == "ordering_user_count")
    values = {
        "id": str(uuid4()),
        "metric_code": item.metric_code,
        "display_name": item.display_name,
        "unit": item.unit,
        "business_definition": item.business_definition,
        "sql_definition": item.sql_definition,
        "dimensions": json.dumps(list(item.dimensions)),
        "source_database": item.source_database,
        "source_table": item.source_table,
        "report_url": item.report_url,
        "generated": item.generated,
        "notice": item.notice,
        "source": item.source,
        "owner": item.owner,
        "status": "ACTIVE",
    }
    op.execute(
        sa.text(
            """
            INSERT INTO metric_definitions (
                id, metric_code, display_name, unit, business_definition, sql_definition,
                dimensions, source_database, source_table, report_url, generated, notice,
                source, owner, status
            ) VALUES (
                CAST(:id AS uuid), :metric_code, :display_name, :unit,
                :business_definition, :sql_definition, CAST(:dimensions AS jsonb),
                :source_database, :source_table, :report_url, :generated, :notice,
                :source, :owner, :status
            ) ON CONFLICT (metric_code) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                unit = EXCLUDED.unit,
                business_definition = EXCLUDED.business_definition,
                sql_definition = EXCLUDED.sql_definition,
                dimensions = EXCLUDED.dimensions,
                source_database = EXCLUDED.source_database,
                source_table = EXCLUDED.source_table,
                report_url = EXCLUDED.report_url,
                generated = EXCLUDED.generated,
                notice = EXCLUDED.notice,
                source = EXCLUDED.source,
                owner = EXCLUDED.owner,
                status = EXCLUDED.status
            """
        ).bindparams(**values)
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM metric_definitions WHERE metric_code = 'ordering_user_count'"))
    op.drop_index("uq_conversations_merchant_daily_report", table_name="conversations")
    op.drop_constraint("ck_conversations_kind", "conversations", type_="check")
    op.drop_column("conversations", "conversation_kind")
