"""v2 售后状态机主记录和订单行级金额快照。"""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin

_MONEY = Numeric(14, 2)


class AfterSale(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "after_sales"
    __table_args__ = (
        CheckConstraint(
            "after_sale_type IN ('RETURN_REFUND','REFUND_ONLY','TICKET')",
            name="ck_after_sales_type",
        ),
        CheckConstraint(
            "state IN ('PENDING_MERCHANT','APPROVED','REJECTED','AWAITING_RETURN',"
            "'RECEIVED','REFUNDED','AWAITING_CUSTOMER_INFO','CLOSED')",
            name="ck_after_sales_state",
        ),
        CheckConstraint("refund_amount >= 0", name="ck_after_sales_refund_amount"),
        CheckConstraint("state_version >= 1", name="ck_after_sales_state_version"),
        CheckConstraint(
            "(conversation_summary_status = 'NOT_SHARED' "
            "AND conversation_summary_text IS NULL AND conversation_summary_reason IS NULL) OR "
            "(conversation_summary_status = 'AVAILABLE' "
            "AND conversation_summary_text IS NOT NULL AND conversation_summary_reason IS NULL) OR "
            "(conversation_summary_status = 'UNAVAILABLE' "
            "AND conversation_summary_text IS NULL AND conversation_summary_reason IS NOT NULL)",
            name="ck_after_sales_conversation_summary",
        ),
        Index("ix_after_sales_merchant_buyer", "merchant_id", "buyer_key"),
        Index("ix_after_sales_merchant_order", "merchant_id", "order_id"),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    buyer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    after_sale_type: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    refund_amount: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    conversation_summary_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="NOT_SHARED"
    )
    conversation_summary_text: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    conversation_summary_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AfterSaleLine(UuidPrimaryKeyMixin, Base):
    __tablename__ = "after_sale_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_after_sale_lines_quantity"),
        CheckConstraint("refund_amount >= 0", name="ck_after_sale_lines_refund_amount"),
        UniqueConstraint("after_sale_id", "order_item_id", name="uq_after_sale_lines_sale_item"),
    )

    after_sale_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("after_sales.id", ondelete="CASCADE"), nullable=False
    )
    order_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)


class AfterSaleSupplement(UuidPrimaryKeyMixin, Base):
    __tablename__ = "after_sale_supplements"
    __table_args__ = (
        Index("ix_after_sale_supplements_sale_time", "after_sale_id", "submitted_at"),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    after_sale_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("after_sales.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str] = mapped_column(String(1000), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AfterSaleReply(UuidPrimaryKeyMixin, Base):
    """审批通过后在平台内送达的独立回复事实；与决定同事务。"""

    __tablename__ = "after_sale_replies"
    __table_args__ = (
        UniqueConstraint("draft_id", name="uq_after_sale_replies_draft"),
        Index("ix_after_sale_replies_sale_time", "after_sale_id", "sent_at"),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    after_sale_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("after_sales.id", ondelete="CASCADE"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="RESTRICT"), nullable=False
    )
    text: Mapped[str] = mapped_column(String(2000), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AfterSaleChallengePreview(Base):
    """一次性确认证据对应的脱敏摘要快照；避免预览后对话变化造成提交内容漂移。"""

    __tablename__ = "after_sale_challenge_previews"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    buyer_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    unavailable_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
