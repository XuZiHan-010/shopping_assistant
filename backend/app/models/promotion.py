"""演示优惠券与商家审批护栏配置。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin

_MONEY = Numeric(14, 2)


class Coupon(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("kind IN ('FULL_REDUCTION','DISCOUNT')", name="ck_coupons_kind"),
        CheckConstraint("ends_at > starts_at", name="ck_coupons_time_window"),
        Index("ix_coupons_merchant_window", "merchant_id", "starts_at", "ends_at"),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    discount_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    product_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)


class GuardrailConfig(UpdatedAtMixin, Base):
    __tablename__ = "guardrail_configs"
    __table_args__ = (
        CheckConstraint("max_discount_rate <= 0.20", name="ck_guardrail_configs_max_discount_rate"),
        CheckConstraint("max_restock_delta > 0", name="ck_guardrail_configs_max_restock_delta"),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), primary_key=True
    )
    max_discount_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("0.20")
    )
    max_price_change_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    min_allowed_price: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    #: 单次补货草稿允许的最大增量；应用时按当时生效的值复检（D9②）。
    max_restock_delta: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("500")
    )
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
