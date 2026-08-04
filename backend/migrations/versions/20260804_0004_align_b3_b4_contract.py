"""Align B3 metric seed with the B4 public query contract.

Revision ID: 20260804_0004
Revises: 20260804_0003
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

from app.metrics.seed import METRIC_SEED

revision: str = "20260804_0004"
down_revision: str | Sequence[str] | None = "20260804_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_CODES: tuple[str, ...] = (
    "order_gmv_amt_1d",
    "order_cnt_1d",
    "order_user_cnt_1d",
    "avg_pay_order_amt_1d",
    "trade_success_gmv_amt_1d",
    "trade_success_order_cnt_1d",
    "refund_amt_1d",
    "refund_rate_1d",
    "return_success_cnt_1d",
    "return_cnt_1d",
    "cs_ticket_cnt_1d",
    "avg_ticket_score_1d",
    "seller_repay_amt_1d",
    "coupon_discount_amt_1d",
    "goods_online_cnt_1d",
    "goods_audit_reject_cnt_1d",
    "appeal_cnt_1d",
    "scm_performance_cnt_1d",
)


def _metric_table() -> sa.Table:
    return sa.table(
        "metric_definitions",
        sa.column("id", sa.UUID()),
        sa.column("metric_code", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("unit", sa.String()),
        sa.column("business_definition", sa.Text()),
        sa.column("sql_definition", sa.Text()),
        sa.column("source", sa.String()),
        sa.column("owner", sa.String()),
        sa.column("status", sa.String()),
    )


def _delete_codes(codes: Sequence[str]) -> None:
    op.execute(
        sa.text("DELETE FROM metric_definitions WHERE metric_code = ANY(:codes)").bindparams(
            sa.bindparam("codes", value=list(codes), type_=sa.ARRAY(sa.String()))
        )
    )


def upgrade() -> None:
    _delete_codes(_LEGACY_CODES)
    op.bulk_insert(
        _metric_table(),
        [
            {
                "id": uuid4(),
                "metric_code": item.metric_code,
                "display_name": item.display_name,
                "unit": item.unit,
                "business_definition": item.business_definition,
                "sql_definition": item.sql_definition,
                "source": item.source,
                "owner": item.owner,
                "status": "ACTIVE",
            }
            for item in METRIC_SEED
        ],
    )


def downgrade() -> None:
    _delete_codes([item.metric_code for item in METRIC_SEED])
    # 0003 is intentionally not replayed during downgrade.  Its seed rows are
    # restored as minimal legacy catalog entries so revision 0003 remains usable.
    op.bulk_insert(
        _metric_table(),
        [
            {
                "id": uuid4(),
                "metric_code": code,
                "display_name": code,
                "unit": "",
                "business_definition": "历史 B3 指标目录条目。",
                "sql_definition": f"SUM({code})",
                "source": "Borough 指标目录",
                "owner": "经营分析组",
                "status": "ACTIVE",
            }
            for code in _LEGACY_CODES
        ],
    )
