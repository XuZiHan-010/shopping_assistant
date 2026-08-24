"""Chat BI 日粒度汇总 ORM；只存可加计数，比率由应用层计算。"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin

COUNTER_COLUMNS = (
    "answer_total",
    "adopted_count",
    "like_count",
    "dislike_count",
    "first_pass_count",
    "business_question_total",
    "hit_count",
    "degraded_count",
    "thinking_sample_count",
)


class ChatBiQaDaily(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """按日期、商家和问题分类汇总的问答计数。"""

    __tablename__ = "chatbi_qa_daily"
    __table_args__ = (
        UniqueConstraint("stat_date", "merchant_id", "category", name="uq_chatbi_qa_daily_grain"),
        Index("ix_chatbi_qa_daily_stat_date", "stat_date"),
        *(
            CheckConstraint(f"{name} >= 0", name=f"ck_chatbi_qa_daily_{name}_nonnegative")
            for name in COUNTER_COLUMNS
        ),
        CheckConstraint(
            "thinking_ms_sum >= 0", name="ck_chatbi_qa_daily_thinking_ms_sum_nonnegative"
        ),
    )

    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    merchant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    answer_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    adopted_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    dislike_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    first_pass_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    business_question_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    degraded_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    thinking_sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    thinking_ms_sum: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
