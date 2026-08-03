"""安全审计和 LLM 用量 ORM。"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UuidPrimaryKeyMixin


class AuditLog(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_merchant_created", "merchant_id", "created_at"),)

    merchant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class LlmUsage(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_usage_date", "usage_date"),)

    merchant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
