"""商家事实层与派生总结层：删除来源后暂停陈旧总结。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID

NOW = datetime(2026, 9, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_deleting_fact_marks_dependent_summary_stale(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from app.memory.merchant_store import MerchantMemoryStore

    store = MerchantMemoryStore(db_session)
    fact = await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="回复语气偏正式",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
    )
    assert fact is not None
    summaries = await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)
    assert len(summaries) == 1 and summaries[0].is_stale is False
    assert str(fact.id) in summaries[0].source_fact_ids
    assert await store.delete_fact(merchant_id=MERCHANT_ONE_ID, fact_id=fact.id) is True
    assert await store.active_summaries(merchant_id=MERCHANT_ONE_ID) == []


@pytest.mark.asyncio
async def test_fact_and_summary_never_cross_merchants(
    db_session: AsyncSession, merchant_one_id: object, merchant_two_id: object
) -> None:
    from app.memory.merchant_store import MerchantMemoryStore

    store = MerchantMemoryStore(db_session)
    fact = await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="回复语气偏正式",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
    )
    assert fact is not None
    await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)
    assert await store.facts(merchant_id=MERCHANT_TWO_ID) == []
    assert await store.active_summaries(merchant_id=MERCHANT_TWO_ID) == []
    assert await store.delete_fact(merchant_id=MERCHANT_TWO_ID, fact_id=fact.id) is False


@pytest.mark.asyncio
async def test_sensitive_fact_rejected_before_write(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from app.memory.merchant_store import MerchantMemoryStore

    result = await MerchantMemoryStore(db_session).add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="电话 13800138000",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
    )
    assert result is None


@pytest.mark.asyncio
async def test_invalid_source_and_oversized_fact_are_rejected(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from app.memory.merchant_store import MerchantMemoryStore

    store = MerchantMemoryStore(db_session)
    assert await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="正式",
        source_ref="invalid", at=NOW,
    ) is None
    assert await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="字" * 2001,
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
    ) is None


@pytest.mark.asyncio
async def test_summary_stays_within_public_contract(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from app.memory.merchant_store import MerchantMemoryStore

    store = MerchantMemoryStore(db_session)
    for _ in range(5):
        assert await store.add_fact(
            merchant_id=MERCHANT_ONE_ID, category="tone", content="字" * 450,
            source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
        ) is not None
    summaries = await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)
    assert len(summaries[0].content) <= 2000
