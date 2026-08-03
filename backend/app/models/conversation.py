"""会话与消息 ORM。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UuidPrimaryKeyMixin,
)


class Conversation(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_merchant_created", "merchant_id", "created_at"),)

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Message(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('USER', 'ASSISTANT', 'SYSTEM')",
            name="ck_messages_role",
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_merchant_created", "merchant_id", "created_at"),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
