"""M3 三张追加写事件账本与历史订单锚事件。

Revision ID: 20260922_0019
Revises: 20260922_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0019"
down_revision: str | Sequence[str] | None = "20260922_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("inventory_events", "fulfillment_events", "after_sale_events")


def upgrade() -> None:
    for table in _TABLES:
        op.create_table(
            table,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "merchant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("merchants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("dedupe_key", sa.String(200), nullable=False),
            sa.Column(
                "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint("dedupe_key", name=f"uq_{table}_dedupe_key"),
        )
        op.create_index(f"ix_{table}_merchant_subject", table, ["merchant_id", "subject_id"])
    op.execute("""
        CREATE FUNCTION forbid_event_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION '% is append-only: UPDATE / DELETE forbidden', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in _TABLES:
        op.execute(f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION forbid_event_mutation()
        """)

    # legacy 订单的 paid_at 可早于 placed_at；事件的事实时间保持原样，重算器按
    # legacy 阶段顺序排序，不把推定时刻误认为实际履约时间。
    # 事件名与冒号拆成 SQL 字符串实参，避免 SQLAlchemy 将 :NAME 当作绑定参数。
    op.execute("""
        INSERT INTO fulfillment_events
          (id, merchant_id, subject_id, event_type, occurred_at, dedupe_key, payload)
        SELECT gen_random_uuid(), merchant_id, id, 'ORDER_PLACED', placed_at,
          concat('legacy:', id::text, ':', 'ORDER_PLACED'),
          jsonb_build_object('origin', 'LEGACY_V1_BACKFILL')
        FROM orders WHERE lifecycle_origin = 'LEGACY_V1'
    """)
    op.execute("""
        INSERT INTO fulfillment_events
          (id, merchant_id, subject_id, event_type, occurred_at, dedupe_key, payload)
        SELECT gen_random_uuid(), merchant_id, id, 'PAYMENT_CONFIRMED', paid_at,
          concat('legacy:', id::text, ':', 'PAYMENT_CONFIRMED'),
          jsonb_build_object('origin', 'LEGACY_V1_BACKFILL')
        FROM orders WHERE lifecycle_origin = 'LEGACY_V1'
          AND order_status IN ('PAID','SHIPPED','COMPLETED')
    """)
    op.execute("""
        INSERT INTO fulfillment_events
          (id, merchant_id, subject_id, event_type, occurred_at, dedupe_key, payload)
        SELECT gen_random_uuid(), merchant_id, id, 'SHIPPED', paid_at + interval '6 hours',
          concat('legacy:', id::text, ':', 'SHIPPED'),
          jsonb_build_object('origin', 'LEGACY_V1_BACKFILL', 'time_inferred', true)
        FROM orders WHERE lifecycle_origin = 'LEGACY_V1'
          AND order_status IN ('SHIPPED','COMPLETED')
    """)
    op.execute("""
        INSERT INTO fulfillment_events
          (id, merchant_id, subject_id, event_type, occurred_at, dedupe_key, payload)
        SELECT gen_random_uuid(), merchant_id, id, 'DELIVERED', paid_at + interval '3 days',
          concat('legacy:', id::text, ':', 'DELIVERED'),
          jsonb_build_object('origin', 'LEGACY_V1_BACKFILL', 'time_inferred', true)
        FROM orders WHERE lifecycle_origin = 'LEGACY_V1' AND order_status = 'COMPLETED'
    """)
    op.execute("""
        INSERT INTO fulfillment_events
          (id, merchant_id, subject_id, event_type, occurred_at, dedupe_key, payload)
        SELECT gen_random_uuid(), merchant_id, id, 'ORDER_CLOSED',
          placed_at + interval '30 minutes',
          concat('legacy:', id::text, ':', 'ORDER_CLOSED'),
          jsonb_build_object('origin', 'LEGACY_V1_BACKFILL', 'time_inferred', true,
                             'close_reason', close_reason)
        FROM orders WHERE lifecycle_origin = 'LEGACY_V1'
          AND order_status IN ('CANCELLED','CLOSED')
    """)


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER trg_{table}_append_only ON {table}")
        op.drop_index(f"ix_{table}_merchant_subject", table_name=table)
        op.drop_table(table)
    op.execute("DROP FUNCTION forbid_event_mutation()")
