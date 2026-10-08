"""双端写入幂等记录，主体只存稳定摘要。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.session import SessionContext
from app.core.session import principal_digest as session_principal_digest
from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin


class IdempotencyRecord(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "role",
            "principal_digest",
            "merchant_id",
            "operation",
            "client_request_id",
            name="uq_idempotency_records_domain",
        ),
        CheckConstraint("role IN ('CUSTOMER','MERCHANT')", name="ck_idempotency_records_role"),
        CheckConstraint(
            "status IN ('PROCESSING','SUCCEEDED','FAILED_RETRYABLE','FAILED_FINAL')",
            name="ck_idempotency_records_status",
        ),
    )

    role: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    client_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'PROCESSING'")
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    @classmethod
    def from_session(
        cls,
        context: SessionContext,
        *,
        secret: bytes,
        operation: str,
        client_request_id: str,
        request_digest: str,
    ) -> IdempotencyRecord:
        """用服务端已验证的会话构造幂等作用域。"""

        return cls(
            role=context.role.value,
            principal_digest=session_principal_digest(context, secret=secret),
            merchant_id=context.merchant_id,
            operation=operation,
            client_request_id=client_request_id,
            request_digest=request_digest,
        )
