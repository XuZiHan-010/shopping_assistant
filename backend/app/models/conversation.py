"""会话与消息 ORM。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
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
        CheckConstraint(
            "(owner_kind IS NULL) = (owner_id IS NULL)", name="ck_conversations_owner_pair"
        ),
        CheckConstraint(
            "owner_kind IS NULL OR owner_kind IN ('GUEST_SESSION','BOUND_PRINCIPAL')",
            name="ck_conversations_owner_kind",
        ),
        Index(
            "ix_conversations_merchant_owner",
            "merchant_id",
            "owner_kind",
            "owner_id",
            postgresql_where=text("owner_kind IS NOT NULL"),
        ),
        CheckConstraint(
            "surface IS NULL OR surface IN ('SHOP','MERCHANT')",
            name="ck_conversations_surface",
        ),
        Index(
            "ix_conversations_directory",
            "merchant_id",
            "surface",
            "owner_kind",
            "owner_id",
            postgresql_where=text("surface IS NOT NULL AND deleted_at IS NULL"),
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
    #: 顾客对话的登录主体（与 `conversation_provenance` 同口径）；商家对话与历史行为空。
    owner_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 创建这段对话的 v2 端（`SHOP` / `MERCHANT`）；v1 对话为空，不进入 v2 会话目录。
    surface: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: 目录软删除时刻；非空后对外一律 403，也不能再被续写。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
    #: v2 助手消息的完整最终响应（与 Chat 响应逐字段相同）；用户消息与 v1 消息为空。
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
