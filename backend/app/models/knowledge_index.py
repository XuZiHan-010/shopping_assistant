"""知识索引版本、分块与生效指针 ORM（PRD A7、§7.6，契约 §6.14，迁移 `20261002_0047`）。

「生效」不是版本状态，而是 `KnowledgeIndexState.active_version_id` 指向的 READY 版本：
原子切换只改这一行，分块永远按版本写入、不原地更新。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from app.models.base import Base

#: 版本状态；ACTIVE 不在其中——生效由指针表达。
INDEX_VERSION_STATUSES = ("BUILDING", "VALIDATING", "READY", "FAILED")
#: 单行指针的固定主键。
INDEX_STATE_ROW_ID = 1


class Vector(UserDefinedType[list[float]]):
    """不带维度的 pgvector 列。

    不引入 `pgvector` Python 包：读写都走 `CAST(:text AS vector)` 的文本字面量
    （见 `app.knowledge.index_versions.vector_literal`），ORM 只需要知道列类型名。
    """

    cache_ok = True

    def get_col_spec(self, **_kw: object) -> str:
        return "vector"


class KnowledgeIndexVersion(Base):
    __tablename__ = "knowledge_index_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('BUILDING', 'VALIDATING', 'READY', 'FAILED')",
            name="ck_knowledge_index_versions_status",
        ),
        CheckConstraint(
            "(status = 'FAILED') = (failure_reason IS NOT NULL)",
            name="ck_knowledge_index_versions_failure_reason",
        ),
        Index(
            "uq_knowledge_index_versions_single_build",
            text("(true)"),
            unique=True,
            postgresql_where=text("status IN ('BUILDING', 'VALIDATING')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corpus_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    recall_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 验证时对照的上一生效版本 Recall@5；首个版本没有对照，为空。
    baseline_recall_at_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 稳定原因码（`IndexFailureReason`），不存异常原文。
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "source_path", "chunk_index", name="uq_knowledge_chunks_version_chunk"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    version_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_index_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)


class KnowledgeIndexState(Base):
    __tablename__ = "knowledge_index_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_knowledge_index_state_single_row"),
        CheckConstraint(
            "stale = (stale_reason IS NOT NULL)", name="ck_knowledge_index_state_stale_reason"
        ),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    active_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("knowledge_index_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    stale_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
