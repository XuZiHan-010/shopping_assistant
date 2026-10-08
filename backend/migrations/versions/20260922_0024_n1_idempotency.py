"""M8：双端写路由的主体隔离幂等记录。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0024"
down_revision: str | Sequence[str] | None = "20260922_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("principal_digest", sa.String(64), nullable=False),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'PROCESSING'")),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "role",
            "principal_digest",
            "merchant_id",
            "operation",
            "client_request_id",
            name="uq_idempotency_records_domain",
        ),
        sa.CheckConstraint("role IN ('CUSTOMER','MERCHANT')", name="ck_idempotency_records_role"),
        sa.CheckConstraint(
            "status IN ('PROCESSING','SUCCEEDED','FAILED_RETRYABLE','FAILED_FINAL')",
            name="ck_idempotency_records_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
