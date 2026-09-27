"""P0 演示经营数据 ORM。

`business_date` 是写入时按 Asia/Shanghai 换算的业务日，也是查询唯一会过滤和
分组的日期列；`*_at` 保留 UTC 时刻用于展示和排查。两者只由 Seed 一处写入。

退款（资金动作）与退货（货品动作）分表：二者可以单独发生，也可以同时发生，
合表会让「退货量」和「退款金额」互相污染。
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin

_MONEY = Numeric(14, 2)


class _MerchantScopedMixin:
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)


class Product(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ONLINE', 'OFFLINE', 'AUDITING', 'REJECTED')",
            name="ck_products_status",
        ),
        CheckConstraint("stock_on_hand >= 0", name="ck_products_stock_on_hand_nonneg"),
        CheckConstraint("stock_reserved >= 0", name="ck_products_stock_reserved_nonneg"),
        CheckConstraint("stock_reserved <= stock_on_hand", name="ck_products_reserved_le_on_hand"),
        CheckConstraint("content_version >= 1", name="ck_products_content_version_positive"),
        UniqueConstraint("merchant_id", "product_code", name="uq_products_merchant_code"),
        Index("ix_products_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_products_merchant_category", "merchant_id", "category"),
    )

    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 与旧版明细宽表对齐的 SPU 标识；早期演示数据可为空，由查询回退到商品编码。
    spu_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    listed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    stock_on_hand: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    stock_reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    stock_available: Mapped[int] = mapped_column(
        Integer, Computed("stock_on_hand - stock_reserved", persisted=True), nullable=False
    )
    low_stock_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    source_locale: Mapped[str] = mapped_column(String(8), nullable=False, server_default="zh-CN")


class Order(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "order_status IN ('CREATED', 'PAID', 'SHIPPED', 'COMPLETED', 'CANCELLED', 'CLOSED')",
            name="ck_orders_status",
        ),
        CheckConstraint(
            "payment_status IN ('PENDING','PAID','CLOSED')", name="ck_orders_payment_status"
        ),
        CheckConstraint(
            "fulfillment_status IN "
            "('NOT_SHIPPED','SHIPPED','IN_TRANSIT','OUT_FOR_DELIVERY','DELIVERED')",
            name="ck_orders_fulfillment_status",
        ),
        CheckConstraint(
            "payment_status <> 'PENDING' OR fulfillment_status = 'NOT_SHIPPED'",
            name="ck_orders_unpaid_not_shipped",
        ),
        CheckConstraint(
            "(payment_status = 'CLOSED') = (close_reason IS NOT NULL)",
            name="ck_orders_closed_reason",
        ),
        CheckConstraint(
            "lifecycle_origin IN ('LEGACY_V1','V2')", name="ck_orders_lifecycle_origin"
        ),
        CheckConstraint(
            "(order_status = 'CREATED' AND payment_status = 'PENDING' "
            "AND fulfillment_status = 'NOT_SHIPPED' AND close_reason IS NULL) OR "
            "(order_status = 'PAID' AND payment_status = 'PAID' "
            "AND fulfillment_status = 'NOT_SHIPPED' AND close_reason IS NULL) OR "
            "(order_status = 'SHIPPED' AND payment_status = 'PAID' "
            "AND fulfillment_status IN ('SHIPPED','IN_TRANSIT','OUT_FOR_DELIVERY') "
            "AND close_reason IS NULL) OR "
            "(order_status = 'COMPLETED' AND payment_status = 'PAID' "
            "AND fulfillment_status = 'DELIVERED' AND close_reason IS NULL) OR "
            "(order_status = 'CANCELLED' AND payment_status = 'CLOSED' "
            "AND fulfillment_status = 'NOT_SHIPPED' AND close_reason = 'CUSTOMER_CANCEL') OR "
            "(order_status = 'CLOSED' AND payment_status = 'CLOSED' "
            "AND fulfillment_status = 'NOT_SHIPPED' AND close_reason = 'TIMEOUT')",
            name="ck_orders_legacy_status_consistent",
        ),
        UniqueConstraint("merchant_id", "order_no", name="uq_orders_merchant_no"),
        Index("ix_orders_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_orders_merchant_status", "merchant_id", "order_status"),
        Index("ix_orders_merchant_address_city", "merchant_id", "address_city_name"),
        Index(
            "ix_orders_v2_pending_placed_at",
            "placed_at",
            postgresql_where=text("payment_status = 'PENDING' AND lifecycle_origin = 'V2'"),
        ),
    )

    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 去重买家用的稳定标识。演示数据不含真实身份信息，只是一个稳定的假名。
    buyer_key: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 收货城市只用于固定的城市聚合模板；允许旧数据为空。
    address_city_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order_status: Mapped[str] = mapped_column(String(16), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_status: Mapped[str] = mapped_column(String(16), nullable=False)
    fulfillment_status: Mapped[str] = mapped_column(String(24), nullable=False)
    after_sale_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="NONE"
    )
    close_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    lifecycle_origin: Mapped[str] = mapped_column(String(16), nullable=False)
    source_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Asia/Shanghai"
    )
    #: v2 订单使用的券；历史订单为空（交易计划 Task 3，迁移 0031）。
    coupon_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("coupons.id", ondelete="RESTRICT", name="fk_orders_coupon_id"),
        nullable=True,
    )
    #: 与 `payment_status = 'CLOSED'` 成对写入；历史关闭订单为空。
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderItem(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint(
            "discount_amount >= 0 AND line_total >= 0", name="ck_order_items_nonnegative_amounts"
        ),
        CheckConstraint(
            "line_total = unit_price * quantity - discount_amount",
            name="ck_order_items_price_snapshot",
        ),
        CheckConstraint("item_amount = line_total", name="ck_order_items_legacy_amount_consistent"),
        Index("ix_order_items_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_order_items_order", "order_id"),
    )

    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    item_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    #: 下单时的商品名称快照（v2 必填，由结账写入）；历史行为空。
    title_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Refund(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint(
            "refund_status IN ('PENDING', 'APPROVED', 'REJECTED', 'REFUNDED')",
            name="ck_refunds_status",
        ),
        Index("ix_refunds_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_refunds_order_item", "order_item_id"),
    )

    order_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    after_sale_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("after_sales.id", ondelete="SET NULL"), nullable=True
    )
    refund_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    refund_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    refund_status: Mapped[str] = mapped_column(String(16), nullable=False)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReturnRecord(_MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "returns"
    __table_args__ = (
        CheckConstraint(
            "return_status IN ('REQUESTED', 'APPROVED', 'REJECTED', 'RECEIVED', 'COMPLETED')",
            name="ck_returns_status",
        ),
        CheckConstraint(
            "logistics_status IN ('PENDING', 'SHIPPED', 'DELIVERED', 'LOST')",
            name="ck_returns_logistics_status",
        ),
        Index("ix_returns_merchant_business_date", "merchant_id", "business_date"),
        Index("ix_returns_order_item", "order_item_id"),
    )

    order_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("order_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    after_sale_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("after_sales.id", ondelete="SET NULL"), nullable=True
    )
    return_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    return_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    return_status: Mapped[str] = mapped_column(String(16), nullable=False)
    logistics_status: Mapped[str] = mapped_column(String(16), nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportTicket(
    _MerchantScopedMixin, UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base
):
    __tablename__ = "support_tickets"
    __table_args__ = (
        CheckConstraint(
            "ticket_status IN ('OPEN', 'PENDING', 'RESOLVED', 'CLOSED')",
            name="ck_support_tickets_status",
        ),
        UniqueConstraint("merchant_id", "ticket_no", name="uq_support_tickets_merchant_no"),
        UniqueConstraint("after_sale_id", name="uq_support_tickets_after_sale_id"),
        Index("ix_support_tickets_merchant_business_date", "merchant_id", "business_date"),
    )

    ticket_no: Mapped[str] = mapped_column(String(64), nullable=False)
    order_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
    )
    after_sale_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("after_sales.id", ondelete="SET NULL"), nullable=True
    )
    ticket_status: Mapped[str] = mapped_column(String(16), nullable=False)
    ticket_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
