"""按商家隔离的追加写事件账本。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UuidPrimaryKeyMixin


class _EventMixin:
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class InventoryEvent(_EventMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "inventory_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_inventory_events_dedupe_key"),
        Index("ix_inventory_events_merchant_subject", "merchant_id", "subject_id"),
    )


class FulfillmentEvent(_EventMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "fulfillment_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_fulfillment_events_dedupe_key"),
        Index("ix_fulfillment_events_merchant_subject", "merchant_id", "subject_id"),
    )


class AfterSaleEvent(_EventMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "after_sale_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_after_sale_events_dedupe_key"),
        Index("ix_after_sale_events_merchant_subject", "merchant_id", "subject_id"),
    )
