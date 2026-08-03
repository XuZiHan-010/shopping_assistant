from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.repositories.conversation import ConversationRepository

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000001")
MERCHANT_TWO_ID = UUID("00000000-0000-0000-0000-000000000002")


async def insert_merchants(session: AsyncSession) -> None:
    session.add_all(
        [
            Merchant(
                id=MERCHANT_ONE_ID,
                merchant_code="borough-demo-100",
                display_name="Borough商家100",
            ),
            Merchant(
                id=MERCHANT_TWO_ID,
                merchant_code="borough-demo-101",
                display_name="Borough商家101",
            ),
        ]
    )
    await session.flush()


@pytest.mark.asyncio
async def test_repository_never_lists_or_reads_other_merchant_conversations(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    own = await repository.create(MERCHANT_ONE_ID, "本商家会话")
    other = await repository.create(MERCHANT_TWO_ID, "其他商家会话")
    await db_session.commit()

    rows = await repository.list_for_merchant(MERCHANT_ONE_ID, limit=20, offset=0)

    assert [row.id for row in rows] == [own.id]
    assert await repository.get_for_merchant(other.id, MERCHANT_ONE_ID) is None
    assert await repository.delete_for_merchant(other.id, MERCHANT_ONE_ID) is False


@pytest.mark.asyncio
async def test_repository_deletes_only_owned_conversation(
    db_session: AsyncSession,
) -> None:
    await insert_merchants(db_session)
    repository = ConversationRepository(db_session)
    own = await repository.create(MERCHANT_ONE_ID, "可删除会话")
    await db_session.commit()

    deleted = await repository.delete_for_merchant(own.id, MERCHANT_ONE_ID)
    await db_session.commit()

    assert deleted is True
    assert await repository.get_for_merchant(own.id, MERCHANT_ONE_ID) is None
