"""商家受控草稿与不可复用的审批结果账本。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin


class Draft(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "drafts"
    __table_args__ = (
        CheckConstraint(
            "state IN ('STAGED','APPLIED','DISCARDED','EXPIRED')", name="ck_drafts_state"
        ),
        CheckConstraint("draft_version >= 1", name="ck_drafts_draft_version"),
        CheckConstraint("target_version >= 0", name="ck_drafts_target_version"),
        CheckConstraint(
            "(batch_id IS NULL) OR (kind = 'CONTENT_CHANGE')",
            name="ck_drafts_batch_id_only_content_change",
        ),
        Index("ix_drafts_merchant_state", "merchant_id", "state"),
        Index("ix_drafts_batch_id", "batch_id", postgresql_where=text("batch_id IS NOT NULL")),
    )

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    target_version: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'STAGED'"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    guardrail_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: N3 阶段 C：商品内容批量起草的批次标识；仅 `CONTENT_CHANGE` 可非空（迁移 `20260925_0037`）。
    batch_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class ChangeLedger(UuidPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "change_ledger"
    __table_args__ = (Index("ix_change_ledger_merchant_created", "merchant_id", "created_at"),)

    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="RESTRICT"), nullable=False
    )
    drafted_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    guardrail_results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
