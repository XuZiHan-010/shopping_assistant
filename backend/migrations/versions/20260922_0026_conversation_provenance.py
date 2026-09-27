"""N1 D：对话来源状态表 `conversation_provenance`（D8④/O2）。

Revision ID: 20260922_0026
Revises: 20260922_0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0026"
down_revision: str | Sequence[str] | None = "20260922_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("principal_kind", sa.String(16), nullable=False),
        sa.Column("principal_id", sa.String(64), nullable=False),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "principal_kind",
            "principal_id",
            "merchant_id",
            "conversation_id",
            "object_type",
            "object_id",
            name="uq_conversation_provenance_scope",
        ),
        sa.CheckConstraint(
            "principal_kind IN ('GUEST_SESSION','BOUND_PRINCIPAL')",
            name="ck_conversation_provenance_principal_kind",
        ),
    )
    op.create_index(
        "ix_conversation_provenance_lookup",
        "conversation_provenance",
        ["principal_kind", "principal_id", "merchant_id", "conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_provenance_lookup", table_name="conversation_provenance")
    op.drop_table("conversation_provenance")
