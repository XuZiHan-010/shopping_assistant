"""P0 指标定义与团队知识 ORM。"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UuidPrimaryKeyMixin,
)


class MetricDefinition(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'DEPRECATED', 'UNVERIFIED')",
            name="ck_metric_definitions_status",
        ),
    )

    metric_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    business_definition: Mapped[str] = mapped_column(Text, nullable=False)
    sql_definition: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )


class KnowledgeDocument(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_knowledge_documents_status",
        ),
        Index("ix_knowledge_documents_category_status", "category", "status"),
    )

    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )
