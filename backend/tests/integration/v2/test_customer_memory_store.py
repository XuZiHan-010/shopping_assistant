"""顾客记忆存储：双键隔离、过期边界及关闭写入竞态。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_v2 import CustomerMemory
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID

NOW = datetime(2026, 9, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_read_excludes_expired_without_renewing_retention(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from tests.support.memory_owners import CustomerStoreFor

    store = CustomerStoreFor(db_session)
    await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="preference",
        key="color", value="blue", at=NOW - timedelta(days=179),
    )
    assert len(await store.recall(merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", at=NOW)) == 1
    assert await store.recall(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", at=NOW + timedelta(days=2)
    ) == []
    row = await db_session.scalar(select(CustomerMemory).where(CustomerMemory.key == "color"))
    assert row is not None and row.last_confirmed_at == NOW - timedelta(days=179)


@pytest.mark.asyncio
async def test_store_isolates_merchant_and_buyer(
    db_session: AsyncSession, merchant_one_id: object, merchant_two_id: object
) -> None:
    from tests.support.memory_owners import CustomerStoreFor

    store = CustomerStoreFor(db_session)
    await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="preference",
        key="color", value="blue", at=NOW,
    )
    assert await store.recall(merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-b", at=NOW) == []
    assert await store.recall(merchant_id=MERCHANT_TWO_ID, buyer_key="buyer-a", at=NOW) == []


@pytest.mark.asyncio
async def test_disable_purges_and_blocks_future_writes(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from tests.support.memory_owners import CustomerStoreFor

    store = CustomerStoreFor(db_session)
    await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="preference",
        key="color", value="blue", at=NOW,
    )
    assert await store.set_preference(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", enabled=False
    ) == 1
    assert await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="preference",
        key="size", value="medium", at=NOW,
    ) is None
    assert await store.recall(merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", at=NOW) == []
    assert await store.memory_enabled(merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a") is False


@pytest.mark.asyncio
async def test_write_updates_same_fact_and_renews_from_confirmation_only(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from tests.support.memory_owners import CustomerStoreFor

    store = CustomerStoreFor(db_session)
    first = await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="preference",
        key="color", value="blue", at=NOW - timedelta(days=3),
    )
    second = await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="preference",
        key="color", value="green", at=NOW,
    )
    assert first is not None and second is not None and first.id == second.id
    rows = await store.recall(merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", at=NOW)
    assert len(rows) == 1 and rows[0].value == "green"
    assert rows[0].last_confirmed_at == NOW


@pytest.mark.asyncio
async def test_same_key_in_different_categories_does_not_overwrite(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    """审查 I6：唯一键须含 category；否则「偏好/颜色」会被「偏好/尺码」静默覆盖。"""

    from tests.support.memory_owners import CustomerStoreFor

    store = CustomerStoreFor(db_session)
    await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="颜色",
        key="偏好", value="素色", at=NOW,
    )
    await store.write(
        merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", category="尺码",
        key="偏好", value="L 码", at=NOW,
    )

    rows = await store.recall(merchant_id=MERCHANT_ONE_ID, buyer_key="buyer-a", at=NOW)

    assert sorted((row.category, row.value) for row in rows) == [("尺码", "L 码"), ("颜色", "素色")]
