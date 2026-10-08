"""商家事实层与派生总结层：删除来源后暂停陈旧总结。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.memory_owners import MerchantStoreFor

NOW = datetime(2026, 9, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_deleting_fact_marks_dependent_summary_stale(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from tests.support.memory_owners import MerchantStoreFor

    store = MerchantStoreFor(db_session)
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
    from tests.support.memory_owners import MerchantStoreFor

    store = MerchantStoreFor(db_session)
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
    from tests.support.memory_owners import MerchantStoreFor

    result = await MerchantStoreFor(db_session).add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="电话 13800138000",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
    )
    assert result is None


@pytest.mark.asyncio
async def test_invalid_source_and_oversized_fact_are_rejected(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    from tests.support.memory_owners import MerchantStoreFor

    store = MerchantStoreFor(db_session)
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
    from tests.support.memory_owners import MerchantStoreFor

    store = MerchantStoreFor(db_session)
    for _ in range(5):
        assert await store.add_fact(
            merchant_id=MERCHANT_ONE_ID, category="tone", content="字" * 450,
            source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
        ) is not None
    summaries = await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)
    assert len(summaries[0].content) <= 2000


@pytest.mark.asyncio
async def test_rebuilt_summary_is_filtered_after_merging_facts(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    """审查 I1：两条各自干净的事实，拼成总结后凑出手机号——真实重建路径必须挡住。"""

    from tests.support.memory_owners import MerchantStoreFor

    store = MerchantStoreFor(db_session)
    first = await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="contact", content="送货前联系 138",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
    )
    second = await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="contact", content="0013 8000 这个号码",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW - timedelta(minutes=1),
    )
    assert first is not None and second is not None  # 单条都能通过写入前过滤
    # 事实按创建时间倒序拼接：较新的「送货前联系 138」在前，与较早的一条拼出 13800138000。

    summaries = await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)

    assert all("138" not in s.content for s in summaries)
    assert await store.active_summaries(merchant_id=MERCHANT_ONE_ID) == []


@pytest.mark.asyncio
async def test_same_preference_from_another_turn_does_not_stack(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    """台账 M5：同一类别、同一内容的偏好在不同回合重复说出，事实层只保留一条。"""

    store = MerchantStoreFor(db_session)
    first = await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="回复语气偏正式",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
    )
    again = await store.add_fact(
        merchant_id=MERCHANT_ONE_ID, category="tone", content="回复语气偏正式",
        source_ref=f"{uuid4()}:{uuid4()}", at=NOW + timedelta(days=1),
    )
    assert first is not None and again is not None and again.id == first.id
    assert len(await store.facts(merchant_id=MERCHANT_ONE_ID)) == 1


@pytest.mark.asyncio
async def test_truncated_summary_only_lists_facts_it_contains(
    db_session: AsyncSession, merchant_one_id: object
) -> None:
    """台账 M6：总结有长度上限；被挡在上限外的事实不得出现在 source_fact_ids 里。"""

    store = MerchantStoreFor(db_session)
    ids = []
    for index in range(5):
        fact = await store.add_fact(
            merchant_id=MERCHANT_ONE_ID, category="tone",
            content=f"偏好第{index}条" + "细" * 590,
            source_ref=f"{uuid4()}:{uuid4()}", at=NOW + timedelta(minutes=index),
        )
        assert fact is not None
        ids.append(str(fact.id))
    [summary] = await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)
    assert len(summary.content) <= 2000
    included = set(summary.source_fact_ids)
    assert included and included < set(ids)
    facts = {str(row.id): row.content for row in await store.facts(merchant_id=MERCHANT_ONE_ID)}
    assert all(facts[fact_id] in summary.content for fact_id in included)
