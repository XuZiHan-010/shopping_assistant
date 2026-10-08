"""N3 C：将净成交额正式口径加入指标资产，而不扩大 v1 单表查询白名单。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260927_0041"
down_revision: str | Sequence[str] | None = "20260925_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("""
        INSERT INTO metric_definitions (
            id, metric_code, display_name, unit, business_definition,
            sql_definition, source, owner, dimensions, source_database,
            source_table, status, generated
        ) VALUES (
            gen_random_uuid(), 'net_gmv', '净成交额', '元',
            '当期按支付日计入的毛成交额减去按退款发生日计入的退款金额。',
            'gross_gmv - refund_amount', 'METRIC_CATALOG', '经营分析组',
            '["date", "category"]'::jsonb, 'public', 'orders/refunds', 'ACTIVE', FALSE
        ) ON CONFLICT (metric_code) DO NOTHING
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        DELETE FROM metric_definitions
        WHERE metric_code = 'net_gmv' AND source = 'METRIC_CATALOG'
    """))
