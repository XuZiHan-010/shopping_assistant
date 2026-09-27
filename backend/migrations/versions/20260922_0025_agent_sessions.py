"""N1 D：会话凭证表 `agent_sessions`，角色与签发来源不可变。

Revision ID: 20260922_0025
Revises: 20260922_0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0025"
down_revision: str | Sequence[str] | None = "20260922_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_fingerprint", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("buyer_key", sa.String(64), nullable=True),
        sa.Column("shop_slug", sa.String(64), nullable=True),
        sa.Column("issuer_fingerprint", sa.String(64), nullable=True),
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
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('CUSTOMER','MERCHANT')", name="ck_agent_sessions_role"),
        sa.CheckConstraint(
            "role <> 'MERCHANT' OR buyer_key IS NULL",
            name="ck_agent_sessions_merchant_no_buyer_key",
        ),
        sa.CheckConstraint(
            "role <> 'MERCHANT' OR shop_slug IS NULL",
            name="ck_agent_sessions_merchant_no_shop_slug",
        ),
        sa.CheckConstraint(
            "role <> 'CUSTOMER' OR issuer_fingerprint IS NULL",
            name="ck_agent_sessions_customer_no_issuer",
        ),
        sa.CheckConstraint(
            "role <> 'CUSTOMER' OR shop_slug IS NOT NULL",
            name="ck_agent_sessions_customer_requires_shop_slug",
        ),
        sa.CheckConstraint(
            "role <> 'MERCHANT' OR issuer_fingerprint IS NOT NULL",
            name="ck_agent_sessions_merchant_requires_issuer",
        ),
    )
    op.create_index(
        "ix_agent_sessions_token_fingerprint", "agent_sessions", ["token_fingerprint"], unique=True
    )
    op.create_index(
        "ix_agent_sessions_issuer_fingerprint", "agent_sessions", ["issuer_fingerprint"]
    )
    op.create_index(
        "ix_agent_sessions_merchant_buyer", "agent_sessions", ["merchant_id", "buyer_key"]
    )

    # CHECK 约束只管单行取值，管不住"签发后换角色/换店铺/换 issuer"。触发器在
    # 数据库层堵住所有写入路径（包括未来的修数据脚本），不只依赖应用层的
    # frozen dataclass（那只防得住"这个进程里的代码"）。
    op.execute("""
        CREATE FUNCTION enforce_agent_session_identity_immutability() RETURNS trigger AS $$
        BEGIN
          IF NEW.role IS DISTINCT FROM OLD.role THEN
            RAISE EXCEPTION 'agent_sessions.role 不可变（AGENTS.md §8.3）';
          END IF;
          IF NEW.merchant_id IS DISTINCT FROM OLD.merchant_id
             OR NEW.shop_slug IS DISTINCT FROM OLD.shop_slug
             OR NEW.issuer_fingerprint IS DISTINCT FROM OLD.issuer_fingerprint THEN
            RAISE EXCEPTION 'agent_sessions 的租户与签发来源不可变';
          END IF;
          IF OLD.buyer_key IS NOT NULL AND NEW.buyer_key IS DISTINCT FROM OLD.buyer_key THEN
            RAISE EXCEPTION '已绑定顾客会话不得切换 buyer_key';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_agent_session_identity_immutability
        BEFORE UPDATE ON agent_sessions
        FOR EACH ROW EXECUTE FUNCTION enforce_agent_session_identity_immutability()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_agent_session_identity_immutability ON agent_sessions")
    op.execute("DROP FUNCTION enforce_agent_session_identity_immutability()")
    op.drop_index("ix_agent_sessions_merchant_buyer", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_issuer_fingerprint", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_token_fingerprint", table_name="agent_sessions")
    op.drop_table("agent_sessions")
