"""商家历史高频问题：频次排序、最近时间破同分、隔离与上限。"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.repositories.answer import AnswerRepository
from app.repositories.conversation import ConversationRepository

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000031")
OTHER_MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000032")


async def _insert_merchants(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Merchant(
                id=MERCHANT_ID,
                merchant_code="top-question-one",
                display_name="高频问题商家一",
            ),
            Merchant(
                id=OTHER_MERCHANT_ID,
                merchant_code="top-question-two",
                display_name="高频问题商家二",
            ),
        ]
    )
    await db_session.flush()


async def _record_answer(
    db_session: AsyncSession,
    *,
    merchant_id: UUID,
    question: str,
    category: str,
    succeeded: bool = True,
) -> None:
    conversations = ConversationRepository(db_session)
    conversation = await conversations.create(merchant_id, question[:20])
    message = await conversations.create_message(merchant_id, conversation.id, "USER", question)
    answer = await conversations.create_processing_answer(
        merchant_id=merchant_id,
        conversation_id=conversation.id,
        user_message_id=message.id,
        client_request_id=str(uuid4()),
        request_digest="0" * 64,
    )
    if not succeeded:
        await conversations.mark_answer_failed(
            answer, retryable=False, error_payload={"code": "TEST"}
        )
    else:
        payload: dict[str, Any] = {"answer": "测试回答", "category": category}
        await conversations.mark_answer_succeeded(answer, payload)
    # PostgreSQL 的 now() 是事务开始时间；逐轮提交才能可靠测试 MAX(created_at)。
    await db_session.commit()


@pytest.mark.asyncio
async def test_top_category_questions_ranks_by_frequency_not_recency(
    db_session: AsyncSession,
) -> None:
    """高频但较早的问题必须排在低频但最新的问题之前。"""

    await _insert_merchants(db_session)
    for _ in range(3):
        await _record_answer(
            db_session,
            merchant_id=MERCHANT_ID,
            question="成交额为什么下降",
            category="TRADE",
        )
    await _record_answer(
        db_session,
        merchant_id=MERCHANT_ID,
        question="昨天成交额多少",
        category="TRADE",
    )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=3
    )

    assert rows[0] == "成交额为什么下降"
    assert "昨天成交额多少" in rows


@pytest.mark.asyncio
async def test_top_category_questions_breaks_ties_by_most_recent(
    db_session: AsyncSession,
) -> None:
    """相同频次时，最近问过的问题排在前面。"""

    await _insert_merchants(db_session)
    for question in ["较远的两次问题"] * 2 + ["较近的两次问题"] * 2:
        await _record_answer(
            db_session,
            merchant_id=MERCHANT_ID,
            question=question,
            category="TRADE",
        )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=2
    )

    assert rows == ["较近的两次问题", "较远的两次问题"]


@pytest.mark.asyncio
async def test_top_category_questions_isolates_merchant_and_category(
    db_session: AsyncSession,
) -> None:
    await _insert_merchants(db_session)
    for merchant_id, category, question in [
        (MERCHANT_ID, "TRADE", "本家交易问题"),
        (MERCHANT_ID, "TRADE", "本家交易问题"),
        (MERCHANT_ID, "REFUND", "本家退款问题"),
        (OTHER_MERCHANT_ID, "TRADE", "别家交易问题"),
    ]:
        await _record_answer(
            db_session,
            merchant_id=merchant_id,
            question=question,
            category=category,
        )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=3
    )

    assert rows == ["本家交易问题"]
    assert "本家退款问题" not in rows
    assert "别家交易问题" not in rows


@pytest.mark.asyncio
async def test_top_category_questions_skips_unsuccessful_answers(
    db_session: AsyncSession,
) -> None:
    await _insert_merchants(db_session)
    await _record_answer(
        db_session,
        merchant_id=MERCHANT_ID,
        question="失败的问题",
        category="TRADE",
        succeeded=False,
    )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=3
    )

    assert rows == []


@pytest.mark.asyncio
async def test_top_category_questions_honours_limit(db_session: AsyncSession) -> None:
    await _insert_merchants(db_session)
    for index in range(5):
        await _record_answer(
            db_session,
            merchant_id=MERCHANT_ID,
            question=f"问题 {index}",
            category="TRADE",
        )

    rows = await AnswerRepository(db_session).top_category_questions(
        merchant_id=MERCHANT_ID, category="TRADE", limit=3
    )

    assert len(rows) == 3
    assert len(set(rows)) == 3
