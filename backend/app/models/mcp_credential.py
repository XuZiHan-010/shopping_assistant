"""`mcp_credentials`：外部 MCP 客户端的短期只读凭证（PRD A8；契约 §8.14.3）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UuidPrimaryKeyMixin


class McpCredential(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    """凭证是密钥不是标识符：库里只存指纹；限定商家、scope 与有效期，撤销只写 `revoked_at`。

    没有签发、撤销或查询凭证的 HTTP 路径——只经 `scripts/mcp_credentials.py`（2026-09-21 用户裁定）。
    """

    __tablename__ = "mcp_credentials"
    __table_args__ = (
        Index("ix_mcp_credentials_token_fingerprint", "token_fingerprint", unique=True),
        Index("ix_mcp_credentials_merchant_id", "merchant_id"),
        CheckConstraint("expires_at > created_at", name="ck_mcp_credentials_window"),
        CheckConstraint(
            "jsonb_typeof(scopes) = 'array' AND jsonb_array_length(scopes) > 0",
            name="ck_mcp_credentials_scopes_non_empty",
        ),
    )

    token_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
