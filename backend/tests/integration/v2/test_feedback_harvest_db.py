"""E6 回流的读库部分（N5 D Task 5）：只取点踩与降级的已完成回合，结果不带任何主体标识。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.eval.feedback_harvest import build_candidates, harvest_samples
from app.models.answer import Answer, Feedback
from app.models.conversation import Conversation, Message
from app.models.merchant import Merchant

pytestmark = pytest.mark.integration


async def _turn(
    session: AsyncSession,
    merchant_id: UUID,
    *,
    question: str,
    payload: dict[str, Any],
    surface: str | None,
    reaction: str | None = None,
    reason: str | None = None,
    status: str = "SUCCEEDED",
) -> None:
    conversation = Conversation(merchant_id=merchant_id, surface=surface)
    session.add(conversation)
    await session.flush()
    message = Message(
        merchant_id=merchant_id,
        conversation_id=conversation.id,
        role="USER",
        content=question,
        source_locale="zh-CN",
    )
    session.add(message)
    await session.flush()
    answer = Answer(
        merchant_id=merchant_id,
        conversation_id=conversation.id,
        user_message_id=message.id,
        client_request_id=f"harvest-{uuid4()}",
        request_digest="digest",
        processing_status=status,
        response_payload=payload,
        response_locale="zh-CN",
        surface=surface,
    )
    session.add(answer)
    await session.flush()
    if reaction is not None:
        session.add(
            Feedback(merchant_id=merchant_id, answer_id=answer.id, reaction=reaction, reason=reason)
        )
    await session.flush()


async def test_harvest_returns_only_disliked_or_degraded_turns_without_identity(
    db_session: AsyncSession,
) -> None:
    shop_a, shop_b = uuid4(), uuid4()
    db_session.add_all(
        [
            Merchant(id=shop_a, merchant_code="harvest-a", display_name="回流店 A"),
            Merchant(id=shop_b, merchant_code="harvest-b", display_name="回流店 B"),
        ]
    )
    await db_session.flush()
    ok = {"answer": "好的", "answer_mode": "CHAT", "degraded": False, "quality_status": "PASSED"}
    degraded = {
        "answer": "暂时无法回答",
        "answer_mode": "METRIC",
        "degraded": True,
        "degraded_reason": "LLM_BUDGET_EXCEEDED",
        "quality_status": "DEGRADED",
    }
    await _turn(
        db_session,
        shop_a,
        question="这条围巾可以退货吗？",
        payload=ok,
        surface="SHOP",
        reaction="DISLIKE",
        reason="答非所问",
    )
    await _turn(db_session, shop_b, question="今天卖得怎么样", payload=degraded, surface="MERCHANT")
    # 下面三条都不该被取到：点赞、正常回答、未完成的回合。
    await _turn(
        db_session, shop_a, question="推荐一双鞋", payload=ok, surface="SHOP", reaction="LIKE"
    )
    await _turn(db_session, shop_b, question="本周订单量", payload=ok, surface="MERCHANT")
    await _turn(
        db_session,
        shop_b,
        question="处理中",
        payload=degraded,
        surface="MERCHANT",
        status="FAILED_FINAL",
    )
    await db_session.commit()
    now = datetime.now(UTC)

    samples = await harvest_samples(
        db_session, since=now - timedelta(hours=1), until=now + timedelta(hours=1)
    )

    assert sorted((s.role, s.signal, s.question) for s in samples) == [
        ("CUSTOMER", "DISLIKE", "这条围巾可以退货吗？"),
        ("MERCHANT", "DEGRADED", "今天卖得怎么样"),
    ]
    disliked = next(s for s in samples if s.signal == "DISLIKE")
    assert disliked.feedback_reason == "答非所问"
    degraded_sample = next(s for s in samples if s.signal == "DEGRADED")
    assert degraded_sample.degraded_reason == "LLM_BUDGET_EXCEEDED"
    assert degraded_sample.answer_mode == "METRIC"
    # 样本与候选里都没有商家标识，也没有回答正文。
    dumped = repr([asdict(s) for s in samples]) + repr(
        [c.to_json() for c in build_candidates(samples, known_fingerprints=frozenset())]
    )
    for leaked in (str(shop_a), str(shop_b), "harvest-a", "回流店", "暂时无法回答"):
        assert leaked not in dumped


async def test_harvest_respects_the_time_window(db_session: AsyncSession) -> None:
    shop = uuid4()
    db_session.add(Merchant(id=shop, merchant_code="harvest-c", display_name="回流店 C"))
    await db_session.flush()
    await _turn(
        db_session,
        shop,
        question="窗口外的问题",
        payload={"answer": "x", "degraded": True, "degraded_reason": "UPSTREAM"},
        surface="SHOP",
    )
    await db_session.commit()
    now = datetime.now(UTC)

    earlier = await harvest_samples(
        db_session, since=now - timedelta(days=3), until=now - timedelta(days=2)
    )

    assert earlier == []
    with pytest.raises(ValueError, match="时间窗"):
        await harvest_samples(db_session, since=now, until=now - timedelta(days=1))
    with pytest.raises(ValueError, match="时间窗"):
        await harvest_samples(db_session, since=datetime(2026, 10, 1), until=now)
