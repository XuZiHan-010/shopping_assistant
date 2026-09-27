"""`conversation_provenance`：单个对话取得的对象访问资格，不跨对话扩散（D8④/O2）。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPrimaryKeyMixin


class ConversationProvenance(UuidPrimaryKeyMixin, Base):
    """登录会话只认证身份，本表才记录“这个主体在这个对话里见过这个对象”。"""

    __tablename__ = "conversation_provenance"
    __table_args__ = (
        UniqueConstraint(
            "principal_kind",
            "principal_id",
            "merchant_id",
            "conversation_id",
            "object_type",
            "object_id",
            name="uq_conversation_provenance_scope",
        ),
        CheckConstraint(
            "principal_kind IN ('GUEST_SESSION','BOUND_PRINCIPAL')",
            name="ck_conversation_provenance_principal_kind",
        ),
        Index(
            "ix_conversation_provenance_lookup",
            "principal_kind",
            "principal_id",
            "merchant_id",
            "conversation_id",
        ),
    )

    principal_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # 访客存内部 session_record_id；已绑定顾客/商家存稳定主体摘要。两者都不是
    # 明文会话凭证或原始 buyer_key（D7⑤同款“别名不可逆”约束）。
    principal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
