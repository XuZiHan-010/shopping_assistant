"""商家 ORM。MVP 不包含用户模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UuidPrimaryKeyMixin,
)


class Merchant(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "merchants"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED')",
            name="ck_merchants_status",
        ),
    )

    merchant_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_demo: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
