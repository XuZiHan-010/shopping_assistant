"""顾客购物车行（PRD C3、D13）：不占库存，价格只作展示，结账时以后端重算为准。

一行只属于一个主体：已绑定顾客（`buyer_key`）或访客会话（`guest_session_id`），二选一。
访客购物车在绑定演示顾客时并入该顾客的购物车并被清空（D7⑥）。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin


class CartLine(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 99", name="ck_cart_items_quantity"),
        CheckConstraint(
            "(buyer_key IS NULL) <> (guest_session_id IS NULL)", name="ck_cart_items_single_owner"
        ),
        Index(
            "uq_cart_items_buyer_product",
            "merchant_id",
            "buyer_key",
            "product_id",
            unique=True,
            postgresql_where=text("buyer_key IS NOT NULL"),
        ),
        Index(
            "uq_cart_items_guest_product",
            "guest_session_id",
            "product_id",
            unique=True,
            postgresql_where=text("guest_session_id IS NOT NULL"),
        ),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    buyer_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guest_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=True
    )
    product_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
