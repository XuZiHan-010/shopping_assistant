"""`SessionService` 的事务边界：并发绑定与购物车合并失败回滚（真实 PostgreSQL）。"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SessionAlreadyBoundConflictError
from app.core.session import SessionAlreadyBoundError
from app.db.session import Database
from app.models.merchant import Merchant
from app.models.session import AgentSession
from app.repositories.merchant import MerchantRepository
from app.repositories.session import SessionRepository
from app.services.session_service import SessionService

DEFAULT_TTL = 86_400


class _RaisingCartMerge:
    async def merge_guest_into_buyer(self, *, session, merchant_id, buyer_key, guest_session_id):
        # N1 尚无购物车表，用同事务内的可观察写入模拟合并执行了一半。
        await session.execute(
            update(Merchant).where(Merchant.id == merchant_id).values(display_name="partial")
        )
        raise RuntimeError("cart merge boom")


@pytest.mark.asyncio
async def test_concurrent_bind_with_different_buyers_only_one_succeeds(
    db_session: AsyncSession,
    integration_database: Database,
    merchant_one_id,
) -> None:
    seed_repo = SessionRepository(db_session, default_ttl_seconds=DEFAULT_TTL)
    _, ctx = await seed_repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")
    await db_session.commit()

    async def attempt(buyer_key: str) -> str:
        async with integration_database.session() as session:
            repo = SessionRepository(session, default_ttl_seconds=DEFAULT_TTL)
            try:
                await repo.bind_demo_customer(ctx, buyer_key=buyer_key)
            except SessionAlreadyBoundError:
                await session.rollback()
                return "rejected"
            await session.commit()
            return "ok"

    outcomes = await asyncio.gather(attempt("bk-1"), attempt("bk-2"))

    assert sorted(outcomes) == ["ok", "rejected"]


@pytest.mark.asyncio
async def test_cart_merge_failure_rolls_back_bind(
    db_session: AsyncSession, merchant_one_id
) -> None:
    sessions_repo = SessionRepository(db_session, default_ttl_seconds=DEFAULT_TTL)
    merchants_repo = MerchantRepository(db_session)
    service = SessionService(
        db_session,
        merchants=merchants_repo,
        sessions=sessions_repo,
        cart_merge=_RaisingCartMerge(),
        demo_customer_identities={"s": "bk-1"},
    )
    _, ctx = await sessions_repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")

    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await service.bind_demo_customer(ctx)

    row = await db_session.get(AgentSession, ctx.session_record_id)
    assert row is not None
    assert row.buyer_key is None
    merchant = await db_session.get(Merchant, merchant_one_id, populate_existing=True)
    assert merchant.display_name == "Borough商家100"


@pytest.mark.asyncio
async def test_bind_demo_customer_retry_does_not_remerge_cart(
    db_session: AsyncSession, merchant_one_id
) -> None:
    class _RecordingCartMerge:
        def __init__(self) -> None:
            self.calls = 0

        async def merge_guest_into_buyer(
            self, *, session, merchant_id, buyer_key, guest_session_id
        ) -> bool:
            self.calls += 1
            return True

    sessions_repo = SessionRepository(db_session, default_ttl_seconds=DEFAULT_TTL)
    merchants_repo = MerchantRepository(db_session)
    cart_merge = _RecordingCartMerge()
    service = SessionService(
        db_session,
        merchants=merchants_repo,
        sessions=sessions_repo,
        cart_merge=cart_merge,
        demo_customer_identities={"s": "bk-1"},
    )
    _, ctx = await sessions_repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")

    first_bound, first_adjusted = await service.bind_demo_customer(ctx)
    second_bound, second_adjusted = await service.bind_demo_customer(first_bound)

    assert first_adjusted is True
    assert second_adjusted is False
    assert cart_merge.calls == 1
    assert first_bound.buyer_key == second_bound.buyer_key == "bk-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("second_buyer", ["bk-1", "bk-2"])
async def test_concurrent_service_binding_merges_once_under_row_lock(
    db_session: AsyncSession, integration_database: Database, merchant_one_id, second_buyer
) -> None:
    repo = SessionRepository(db_session, default_ttl_seconds=DEFAULT_TTL)
    _, guest = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")
    await db_session.commit()
    merge_entered = asyncio.Event()
    release_merge = asyncio.Event()
    second_started = asyncio.Event()

    class RecordingMerge:
        calls = 0

        async def merge_guest_into_buyer(self, **kwargs):
            self.calls += 1
            merge_entered.set()
            await asyncio.wait_for(release_merge.wait(), timeout=5)
            return True

    cart = RecordingMerge()

    async def attempt(buyer, *, second=False):
        async with integration_database.session() as session:
            service = SessionService(
                session,
                merchants=MerchantRepository(session),
                sessions=SessionRepository(session, default_ttl_seconds=DEFAULT_TTL),
                cart_merge=cart,
                demo_customer_identities={"s": buyer},
            )
            if second:
                second_started.set()
            try:
                result = await service.bind_demo_customer(guest)
                await session.commit()
                return result[1]
            except SessionAlreadyBoundConflictError as exc:
                await session.rollback()
                return exc.status_code

    first = asyncio.create_task(attempt("bk-1"))
    try:
        await asyncio.wait_for(merge_entered.wait(), timeout=5)
        second = asyncio.create_task(attempt(second_buyer, second=True))
        await asyncio.wait_for(second_started.wait(), timeout=5)
    finally:
        release_merge.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=10)
    assert results == [True, False if second_buyer == "bk-1" else 409]
    assert cart.calls == 1
    async with integration_database.session() as session:
        row = await session.get(AgentSession, guest.session_record_id)
        assert row.buyer_key == "bk-1"
