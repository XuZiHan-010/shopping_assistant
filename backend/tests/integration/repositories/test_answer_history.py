"""记忆沉淀的历史问答输入：商家与分类范围。

这些用例存在的理由是一次真实缺陷：`memory_agent` 曾把 `history=[]` 硬编码传给
`MemoryService.consolidate()`，参考项目却是把该商家该分类的近期问答一并压缩。
当时 899 条测试全绿——因为没有任何一条断言沉淀的**输入内容**。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.repositories.answer import AnswerRepository
from app.repositories.conversation import ConversationRepository

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000021")
MERCHANT_TWO_ID = UUID("00000000-0000-0000-0000-000000000022")


async def insert_merchants(session: AsyncSession) -> None:
    session.add_all(
        [
            Merchant(
                id=MERCHANT_ONE_ID,
                merchant_code="answer-history-merchant-one",
                display_name="历史问答商家一",
            ),
            Merchant(
                id=MERCHANT_TWO_ID,
                merchant_code="answer-history-merchant-two",
                display_name="历史问答商家二",
            ),
        ]
    )
    await session.flush()


async def record_answer(
    session: AsyncSession,
    *,
    merchant_id: UUID,
    question: str,
    answer_text: str,
    category: str | None,
    succeeded: bool = True,
) -> None:
    """写入一轮完整问答，尽量走生产仓储而不是手搓 ORM。

    每轮单独 ``commit``：PostgreSQL 的 ``now()`` 返回**事务开始时间**，把多轮塞进
    同一个事务会让它们的 ``created_at`` 完全相同，排序断言就测不出真实先后。
    生产中一次请求就是一个事务，这里保持一致。
    """

    conversations = ConversationRepository(session)
    conversation = await conversations.create(merchant_id, question[:20])
    message = await conversations.create_message(merchant_id, conversation.id, "USER", question)
    answer = await conversations.create_processing_answer(
        merchant_id=merchant_id,
        conversation_id=conversation.id,
        user_message_id=message.id,
        client_request_id=f"{merchant_id}-{question}",
        request_digest="0" * 64,
    )
    if not succeeded:
        await conversations.mark_answer_failed(
            answer, retryable=False, error_payload={"code": "TEST"}
        )
        await session.commit()
        return
    payload: dict[str, Any] = {"answer": answer_text, "category": category}
    await conversations.mark_answer_succeeded(answer, payload)
    await session.commit()


@pytest.mark.asyncio
async def test_recent_answers_returns_only_same_merchant_and_category(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    await record_answer(
        db_session,
        merchant_id=MERCHANT_ONE_ID,
        question="上周成交额多少",
        answer_text="上周成交额 12 万元",
        category="TRADE",
    )
    await record_answer(
        db_session,
        merchant_id=MERCHANT_ONE_ID,
        question="上周退款多少",
        answer_text="上周退款 3 千元",
        category="REFUND",
    )
    await record_answer(
        db_session,
        merchant_id=MERCHANT_TWO_ID,
        question="别家的成交额",
        answer_text="别家成交额 99 万元",
        category="TRADE",
    )
    await db_session.commit()

    rows = await AnswerRepository(db_session).recent_answers_for_category(
        merchant_id=MERCHANT_ONE_ID, category="TRADE", limit=80
    )

    serialized = str(rows)
    assert len(rows) == 1
    assert "上周成交额 12 万元" in serialized
    assert "上周成交额多少" in serialized
    # 其他分类与其他商家的内容一个字都不能出现在沉淀输入里。
    assert "退款" not in serialized
    assert "别家" not in serialized
    assert "99 万元" not in serialized


@pytest.mark.asyncio
async def test_recent_answers_skips_unsuccessful_answers(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    await record_answer(
        db_session,
        merchant_id=MERCHANT_ONE_ID,
        question="失败的问题",
        answer_text="",
        category="TRADE",
        succeeded=False,
    )
    await db_session.commit()

    rows = await AnswerRepository(db_session).recent_answers_for_category(
        merchant_id=MERCHANT_ONE_ID, category="TRADE", limit=80
    )

    assert rows == []


@pytest.mark.asyncio
async def test_recent_answers_orders_newest_first_and_honours_limit(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    for index in range(3):
        await record_answer(
            db_session,
            merchant_id=MERCHANT_ONE_ID,
            question=f"第{index}问",
            answer_text=f"第{index}答",
            category="TRADE",
        )
    await db_session.commit()

    rows = await AnswerRepository(db_session).recent_answers_for_category(
        merchant_id=MERCHANT_ONE_ID, category="TRADE", limit=2
    )

    assert len(rows) == 2
    assert "第2答" in str(rows[0])
    assert "第1答" in str(rows[1])
