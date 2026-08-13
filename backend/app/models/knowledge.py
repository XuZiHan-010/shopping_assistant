"""P0 指标定义与团队知识 ORM。"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.metrics.report_url import normalize_report_url
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
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    dimensions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_database: Mapped[str] = mapped_column(String(64), nullable=False)
    source_table: Mapped[str] = mapped_column(String(64), nullable=False)
    report_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notice: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'ACTIVE'"),
    )

    @validates("report_url")
    def normalize_report_url_value(self, _key: str, value: str | None) -> str | None:
        return normalize_report_url(value)


class KnowledgeDocument(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name="ck_knowledge_documents_status",
        ),
        Index("ix_knowledge_documents_category_status", "category", "status"),
        Index("uq_knowledge_documents_source_path", "source_path", unique=True),
    )

    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    # 检索按「路径 + 正文」匹配；路径携带业务域与文档类型，不能丢弃。
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    # 命中旧 Wiki 的骨架文档时，B5 必须向商家说明资料尚不完整。
    is_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
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
