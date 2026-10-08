"""M5：优惠券与商家护栏配置。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0021"
down_revision: str | Sequence[str] | None = "20260922_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    money = sa.Numeric(14, 2)
    op.create_table(
        "coupons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("threshold_amount", money, nullable=True),
        sa.Column("discount_amount", money, nullable=True),
        sa.Column("discount_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("product_ids", postgresql.JSONB(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("kind IN ('FULL_REDUCTION','DISCOUNT')", name="ck_coupons_kind"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_coupons_time_window"),
    )
    op.create_index(
        "ix_coupons_merchant_window", "coupons", ["merchant_id", "starts_at", "ends_at"]
    )
    op.create_table(
        "guardrail_configs",
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "max_discount_rate", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.20")
        ),
        sa.Column("max_price_change_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("min_allowed_price", money, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.CheckConstraint(
            "max_discount_rate <= 0.20", name="ck_guardrail_configs_max_discount_rate"
        ),
    )


def downgrade() -> None:
    op.drop_table("guardrail_configs")
    op.drop_index("ix_coupons_merchant_window", table_name="coupons")
    op.drop_table("coupons")
