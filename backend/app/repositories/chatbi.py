"""Chat BI 汇总表的幂等物化与读取。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import ColumnElement, Date, Select, and_, cast, delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert

from app.analytics.chatbi_metrics import QaCounters
from app.db.session import Database
from app.models.answer import Answer, Feedback
from app.models.chatbi import ChatBiQaDaily


@dataclass(frozen=True)
class DailyRow:
    stat_date: date
    merchant_id: UUID
    category: str
    counters: QaCounters


class ChatBiRepository:
    def __init__(self, database: Database, *, business_timezone: str = "Asia/Shanghai") -> None:
        self._database = database
        self._timezone = business_timezone

    def _stat_date(self) -> ColumnElement[date]:
        return cast(func.timezone(self._timezone, Answer.created_at), Date)

    def _source_select(
        self, start_date: date, end_date: date
    ) -> Select[
        tuple[date, UUID, str, int, int, int, int, int, int, int, int, int, int]
    ]:
        payload = Answer.response_payload
        stat_date = self._stat_date().label("stat_date")
        category = func.coalesce(payload["category"].astext, literal("UNKNOWN"))
        is_business = payload["answer_mode"].astext != literal("CHAT")
        is_hit = and_(
            payload["answer_mode"].astext.notin_(("CHAT", "INVALID")),
            payload["analysis_sources"].astext != literal('["NONE"]'),
        )
        is_first_pass = and_(
            payload["quality_status"].astext == literal("PASSED"),
            payload["quality_attempts"].astext == literal("1"),
        )
        is_failure = func.coalesce(
            payload["degraded"].astext == literal("true"), literal(False)
        ) | payload["quality_status"].astext.in_(("DEGRADED", "FAILED"))
        return (
            select(
                stat_date,
                Answer.merchant_id.label("merchant_id"),
                category.label("category"),
                func.count().label("answer_total"),
                func.count().filter(Feedback.is_adopted.is_(True)).label("adopted_count"),
                func.count().filter(Feedback.reaction == "LIKE").label("like_count"),
                func.count().filter(Feedback.reaction == "DISLIKE").label("dislike_count"),
                func.count().filter(is_first_pass).label("first_pass_count"),
                func.count().filter(is_business).label("business_question_total"),
                func.count().filter(is_hit).label("hit_count"),
                func.count().filter(is_failure).label("degraded_count"),
                func.count().filter(Answer.elapsed_ms.isnot(None)).label("thinking_sample_count"),
                func.coalesce(func.sum(Answer.elapsed_ms), 0).label("thinking_ms_sum"),
            )
            .select_from(Answer)
            .outerjoin(Feedback, Feedback.answer_id == Answer.id)
            .where(
                Answer.processing_status == "SUCCEEDED",
                stat_date >= start_date,
                stat_date <= end_date,
            )
            .group_by(stat_date, Answer.merchant_id, category)
        )

    async def rollup_range(self, *, start_date: date, end_date: date) -> int:
        async with self._database.session() as session, session.begin():
            rows = (await session.execute(self._source_select(start_date, end_date))).all()
            await session.execute(
                delete(ChatBiQaDaily).where(
                    ChatBiQaDaily.stat_date >= start_date, ChatBiQaDaily.stat_date <= end_date
                )
            )
            if not rows:
                return 0
            await session.execute(
                insert(ChatBiQaDaily).values(
                    [
                        {
                            "id": uuid4(),
                            "stat_date": row.stat_date,
                            "merchant_id": row.merchant_id,
                            "category": row.category,
                            "answer_total": row.answer_total,
                            "adopted_count": row.adopted_count,
                            "like_count": row.like_count,
                            "dislike_count": row.dislike_count,
                            "first_pass_count": row.first_pass_count,
                            "business_question_total": row.business_question_total,
                            "hit_count": row.hit_count,
                            "degraded_count": row.degraded_count,
                            "thinking_sample_count": row.thinking_sample_count,
                            "thinking_ms_sum": row.thinking_ms_sum,
                        }
                        for row in rows
                    ]
                )
            )
            return len(rows)

    async def load_daily(self, *, start_date: date, end_date: date) -> list[DailyRow]:
        async with self._database.session() as session:
            result = await session.execute(
                select(ChatBiQaDaily)
                .where(ChatBiQaDaily.stat_date >= start_date, ChatBiQaDaily.stat_date <= end_date)
                .order_by(ChatBiQaDaily.stat_date, ChatBiQaDaily.category)
            )
            return [
                DailyRow(
                    row.stat_date,
                    row.merchant_id,
                    row.category,
                    QaCounters(
                        row.answer_total,
                        row.adopted_count,
                        row.like_count,
                        row.dislike_count,
                        row.first_pass_count,
                        row.business_question_total,
                        row.hit_count,
                        row.degraded_count,
                        row.thinking_sample_count,
                        row.thinking_ms_sum,
                    ),
                )
                for row in result.scalars()
            ]
