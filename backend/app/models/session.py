"""`agent_sessions`：双端会话凭证的服务端记录（D7/D8）。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin


class AgentSession(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """会话是凭证不是标识符：库里只存指纹，角色与签发来源不可变。"""

    __tablename__ = "agent_sessions"
    __table_args__ = (
        Index("ix_agent_sessions_token_fingerprint", "token_fingerprint", unique=True),
        Index("ix_agent_sessions_issuer_fingerprint", "issuer_fingerprint"),
        Index("ix_agent_sessions_merchant_buyer", "merchant_id", "buyer_key"),
        CheckConstraint("role IN ('CUSTOMER','MERCHANT')", name="ck_agent_sessions_role"),
        CheckConstraint(
            "role <> 'MERCHANT' OR buyer_key IS NULL",
            name="ck_agent_sessions_merchant_no_buyer_key",
        ),
        CheckConstraint(
            "role <> 'MERCHANT' OR shop_slug IS NULL",
            name="ck_agent_sessions_merchant_no_shop_slug",
        ),
        CheckConstraint(
            "role <> 'CUSTOMER' OR issuer_fingerprint IS NULL",
            name="ck_agent_sessions_customer_no_issuer",
        ),
        CheckConstraint(
            "role <> 'CUSTOMER' OR shop_slug IS NOT NULL",
            name="ck_agent_sessions_customer_requires_shop_slug",
        ),
        CheckConstraint(
            "role <> 'MERCHANT' OR issuer_fingerprint IS NOT NULL",
            name="ck_agent_sessions_merchant_requires_issuer",
        ),
    )

    token_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    buyer_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shop_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issuer_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
