"""日报系统会话必须有数据库唯一约束，不能靠标题或进程内状态维持。"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.repositories.conversation import ConversationRepository


@pytest.mark.asyncio
async def test_daily_report_conversation_is_unique_per_merchant_and_hidden_from_chat_list(
    db_session: AsyncSession,
    merchant_one_id: UUID,
    merchant_two_id: UUID,
) -> None:
    repository = ConversationRepository(db_session)

    first = await repository.get_or_create_daily_report_conversation(merchant_one_id)
    repeated = await repository.get_or_create_daily_report_conversation(merchant_one_id)
    other_merchant = await repository.get_or_create_daily_report_conversation(merchant_two_id)
    normal_chat = await repository.create(merchant_one_id, "普通会话")

    assert first.id == repeated.id
    assert first.conversation_kind == "DAILY_REPORT"
    assert other_merchant.id != first.id
    listed = await repository.list_for_merchant(merchant_one_id, limit=20, offset=0)
    assert [row.id for row in listed] == [normal_chat.id]

    db_session.add(
        Conversation(
            merchant_id=merchant_one_id,
            title="不应允许的第二条日报会话",
            conversation_kind="DAILY_REPORT",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
