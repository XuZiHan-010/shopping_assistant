"""N5 A：MCP 只读凭证表 `mcp_credentials`（PRD A8；契约 §8.14.3）。

库里只存凭证指纹；签发、撤销只经后端命令行脚本，没有 HTTP 路径。
商家删除时级联删除其凭证——凭证不是需要保留的业务历史。

Revision ID: 20261003_0048
Revises: 20261002_0047
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261003_0048"
down_revision: str | Sequence[str] | None = "20261002_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "merchant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("expires_at > created_at", name="ck_mcp_credentials_window"),
        sa.CheckConstraint(
            "jsonb_typeof(scopes) = 'array' AND jsonb_array_length(scopes) > 0",
            name="ck_mcp_credentials_scopes_non_empty",
        ),
    )
    op.create_index(
        "ix_mcp_credentials_token_fingerprint",
        "mcp_credentials",
        ["token_fingerprint"],
        unique=True,
    )
    op.create_index("ix_mcp_credentials_merchant_id", "mcp_credentials", ["merchant_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_credentials_merchant_id", table_name="mcp_credentials")
    op.drop_index("ix_mcp_credentials_token_fingerprint", table_name="mcp_credentials")
    op.drop_table("mcp_credentials")
