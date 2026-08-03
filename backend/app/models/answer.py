"""回答和反馈 ORM。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UuidPrimaryKeyMixin,
)


class Answer(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "answers"
    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('PROCESSING', 'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED_FINAL')",
            name="ck_answers_processing_status",
        ),
        UniqueConstraint(
            "merchant_id",
            "client_request_id",
            name="uq_answers_merchant_client_request",
        ),
        Index("ix_answers_conversation_created", "conversation_id", "created_at"),
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
    user_message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default=text("'PROCESSING'"),
    )
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Feedback(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "reaction IS NULL OR reaction IN ('LIKE', 'DISLIKE')",
            name="ck_feedback_reaction",
        ),
        UniqueConstraint(
            "merchant_id",
            "answer_id",
            name="uq_feedback_merchant_answer",
        ),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    answer_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("answers.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_adopted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    reaction: Mapped[str | None] = mapped_column(String(16), nullable=True)
