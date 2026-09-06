"""Chat BI Rollup 的正确性和幂等性。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import reduce
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.chatbi_metrics import QaCounters
from app.db.session import Database
from app.localization.locales import SourceLanguage
from app.models.answer import Answer, Feedback
from app.models.conversation import Conversation
from app.models.merchant import Merchant
from app.repositories.chatbi import ChatBiRepository

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000041")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000042")
STAT_DAY = date(2026, 8, 20)
CREATED_AT = datetime(2026, 8, 20, 4, 0, tzinfo=UTC)


async def _seed(session: AsyncSession) -> None:
    session.add(
        Merchant(id=MERCHANT_ID, merchant_code="chatbi-rollup", display_name="Chat BI 汇总测试商家")
    )
    await session.flush()
    session.add(Conversation(id=CONVERSATION_ID, merchant_id=MERCHANT_ID, title="汇总测试"))
    await session.flush()
    specs = [
        ("METRIC", "PASSED", ["DATABASE"], True, "LIKE", 1200),
        ("RULE", "PASSED", ["KNOWLEDGE"], False, "DISLIKE", 800),
        ("CHAT", "NOT_RUN", ["NONE"], False, None, 400),
    ]
    for index, (mode, status, sources, adopted, reaction, elapsed) in enumerate(specs):
        answer = Answer(
            id=uuid4(),
            merchant_id=MERCHANT_ID,
            conversation_id=CONVERSATION_ID,
            client_request_id=f"rollup-{index}",
            request_digest=f"digest-{index}",
            processing_status="SUCCEEDED",
            response_payload={
                "answer_mode": mode,
                "category": "TRADE",
                "quality_status": status,
                "quality_attempts": 1,
                "analysis_sources": sources,
                "degraded": False,
            },
            elapsed_ms=elapsed,
            created_at=CREATED_AT,
            response_locale=str(SourceLanguage.UND),
        )
        session.add(answer)
        await session.flush()
        session.add(
            Feedback(
                id=uuid4(),
                merchant_id=MERCHANT_ID,
                answer_id=answer.id,
                is_adopted=adopted,
                reaction=reaction,
            )
        )
    await session.commit()


@pytest.mark.asyncio
async def test_rollup_counts_source_and_removes_stale_rows(
    db_session: AsyncSession, integration_database: Database
) -> None:
    """取消重算前清除窗口或修改任一聚合口径时，本测试应失败。"""
    await _seed(db_session)
    repository = ChatBiRepository(integration_database)
    await repository.rollup_range(start_date=STAT_DAY, end_date=STAT_DAY)
    rows = await repository.load_daily(start_date=STAT_DAY, end_date=STAT_DAY)
    totals = reduce(QaCounters.merge, (row.counters for row in rows), QaCounters.zero())
    assert (totals.answer_total, totals.business_question_total, totals.hit_count) == (3, 2, 2)
    assert (
        totals.adopted_count,
        totals.like_count,
        totals.dislike_count,
        totals.thinking_ms_sum,
    ) == (1, 1, 1, 2400)
    first = rows
    await repository.rollup_range(start_date=STAT_DAY, end_date=STAT_DAY)
    assert await repository.load_daily(start_date=STAT_DAY, end_date=STAT_DAY) == first
    await db_session.execute(text("DELETE FROM feedback; DELETE FROM answers"))
    await db_session.commit()
    await repository.rollup_range(start_date=STAT_DAY, end_date=STAT_DAY)
    assert await repository.load_daily(start_date=STAT_DAY, end_date=STAT_DAY) == []
