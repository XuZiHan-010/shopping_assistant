"""Chat Repository 的 PostgreSQL 集成测试。"""

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.repositories.conversation import ConversationRepository

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000011")
MERCHANT_TWO_ID = UUID("00000000-0000-0000-0000-000000000012")


async def _insert_merchants(session: AsyncSession) -> None:
    session.add_all(
        [
            Merchant(
                id=MERCHANT_ONE_ID,
                merchant_code="borough-chat-100",
                display_name="Borough商家100",
            ),
            Merchant(
                id=MERCHANT_TWO_ID,
                merchant_code="borough-chat-101",
                display_name="Borough商家101",
            ),
        ]
    )
    await session.flush()


@pytest.mark.asyncio
async def test_answer_idempotency_lookup_is_scoped_to_merchant(
    db_session: AsyncSession,
) -> None:
    await _insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    conversation = await repository.create(MERCHANT_ONE_ID, "商家一会话")
    message = await repository.create_message(MERCHANT_ONE_ID, conversation.id, "USER", "昨天 GMV")
    answer = await repository.create_processing_answer(
        MERCHANT_ONE_ID,
        conversation.id,
        message.id,
        "request-1",
        "a" * 64,
    )
    await db_session.commit()

    own = await repository.get_answer_by_client_request(MERCHANT_ONE_ID, "request-1")
    other = await repository.get_answer_by_client_request(MERCHANT_TWO_ID, "request-1")

    assert own is not None
    assert own.id == answer.id
    assert other is None
