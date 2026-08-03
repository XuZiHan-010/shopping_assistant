import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant
from app.services.seed_service import default_merchants, seed_demo_merchants


@pytest.mark.asyncio
async def test_seed_creates_three_merchants_without_duplicates(
    db_session: AsyncSession,
) -> None:
    merchants = default_merchants(merchant_count=3)

    first = await seed_demo_merchants(db_session, merchants)
    second = await seed_demo_merchants(db_session, merchants)
    count = await db_session.scalar(select(func.count()).select_from(Merchant))

    assert first.created == 3
    assert first.existing == 0
    assert second.created == 0
    assert second.existing == 3
    assert count == 3
