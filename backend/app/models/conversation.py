"""会话与消息 ORM。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
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
    __table_args__ = (
        CheckConstraint(
            "conversation_kind IN ('CHAT', 'DAILY_REPORT')",
            name="ck_conversations_kind",
        ),
        Index("ix_conversations_merchant_created", "merchant_id", "created_at"),
        Index(
            "uq_conversations_merchant_daily_report",
            "merchant_id",
            unique=True,
            postgresql_where=text("conversation_kind = 'DAILY_REPORT'"),
        ),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    conversation_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'CHAT'")
    )


class Message(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('USER', 'ASSISTANT', 'SYSTEM')",
            name="ck_messages_role",
        ),
        CheckConstraint(
            "source_locale IN ('zh-CN', 'en-US', 'mixed', 'und')",
            name="ck_messages_source_locale",
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
    # 消息正文本身使用的语言（`SourceLanguage`），不是显示语言；由
    # `20260831_0016_content_locale_metadata` 迁移对历史行按 `content` 分类回填，
    # 禁止用数据库默认值统一标成 `zh-CN`。见 `app/localization/locales.py`。
    source_locale: Mapped[str] = mapped_column(String(16), nullable=False)
