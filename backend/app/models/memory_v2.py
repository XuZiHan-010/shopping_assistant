"""按商家和顾客隔离的 v2 记忆、信号及当日简报。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UuidPrimaryKeyMixin


class CustomerMemory(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "customer_memories"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "buyer_key", "category", "key", name="uq_customer_memories_owner_key"
        ),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    buyer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str] = mapped_column(String(2000), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MerchantMemoryFact(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "merchant_memory_facts"
    __table_args__ = (Index("ix_merchant_memory_facts_merchant", "merchant_id"),)

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(String(4000), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MerchantMemorySummary(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "merchant_memory_summaries"
    __table_args__ = (
        Index("ix_merchant_memory_summaries_merchant", "merchant_id"),
        UniqueConstraint("merchant_id", "category", name="uq_merchant_memory_summaries_category"),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(String(4000), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    rebuilt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source_fact_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


class CustomerMemoryPreference(Base):
    __tablename__ = "customer_memory_preferences"

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    buyer_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class MemoryExtractionJob(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "memory_extraction_jobs"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_memory_extraction_jobs_message"),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','DONE','FAILED')",
            name="ck_memory_extraction_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_memory_extraction_jobs_attempts"),
        Index("ix_memory_extraction_jobs_claim", "status", "lease_until"),
    )

    message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'PENDING'")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CustomerSignal(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "customer_signals"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('RETURN_REQUESTS','REFUND_REQUESTS','SUPPORT_TICKETS','CONTENT_GAP')",
            name="ck_customer_signals_kind",
        ),
        CheckConstraint("count > 0", name="ck_customer_signals_count"),
        Index("ix_customer_signals_merchant_date", "merchant_id", "signal_date"),
        Index(
            "uq_customer_signals_daily_product", "merchant_id", "kind", "product_id",
            "signal_date", unique=True,
            postgresql_where=text("product_id IS NOT NULL"),
        ),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    product_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signal_date: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    derived_from: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    is_ignored: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ignore_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class DailyBrief(UuidPrimaryKeyMixin, Base):
    __tablename__ = "daily_briefs"
    __table_args__ = (
        UniqueConstraint("merchant_id", "business_date", name="uq_daily_briefs_merchant_date"),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    brief_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
