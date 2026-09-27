"""M4：受控草稿与变更账本。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0020"
down_revision: str | Sequence[str] | None = "20260922_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_version", sa.Integer(), nullable=False),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("state", sa.String(16), nullable=False, server_default=sa.text("'STAGED'")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("guardrail_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('STAGED','APPLIED','DISCARDED','EXPIRED')", name="ck_drafts_state"
        ),
        sa.CheckConstraint("draft_version >= 1", name="ck_drafts_draft_version"),
        sa.CheckConstraint("target_version >= 0", name="ck_drafts_target_version"),
    )
    op.create_index("ix_drafts_merchant_state", "drafts", ["merchant_id", "state"])
    op.create_table(
        "change_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("drafted_by", sa.String(128), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("guardrail_results", postgresql.JSONB(), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_change_ledger_merchant_created", "change_ledger", ["merchant_id", "created_at"]
    )
    op.execute("""
        CREATE FUNCTION guard_draft_terminal_state() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.state IN ('APPLIED', 'DISCARDED', 'EXPIRED')
               AND NEW.state IS DISTINCT FROM OLD.state THEN
                RAISE EXCEPTION '终态草稿不得重新进入其他状态';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER trg_drafts_terminal_state BEFORE UPDATE OF state ON drafts
        FOR EACH ROW EXECUTE FUNCTION guard_draft_terminal_state()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_drafts_terminal_state ON drafts")
    op.execute("DROP FUNCTION guard_draft_terminal_state()")
    op.drop_index("ix_change_ledger_merchant_created", table_name="change_ledger")
    op.drop_table("change_ledger")
    op.drop_index("ix_drafts_merchant_state", table_name="drafts")
    op.drop_table("drafts")
