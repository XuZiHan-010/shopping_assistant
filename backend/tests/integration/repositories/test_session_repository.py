"""会话仓储：签发、解析、绑定与级联撤销（真实 PostgreSQL）。"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import MerchantContext
from app.core.session import SessionAlreadyBoundError, issuer_fingerprint
from app.models.session import AgentSession
from app.repositories.session import SessionRepository

DEFAULT_TTL = 86_400


def _repo(session: AsyncSession, ttl: int = DEFAULT_TTL) -> SessionRepository:
    return SessionRepository(session, default_ttl_seconds=ttl)


@pytest.mark.asyncio
async def test_issued_token_is_not_stored_in_plaintext(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    token, _ = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="borough-100")

    rows = (await db_session.execute(select(AgentSession))).scalars().all()
    dumped = str([row.__dict__ for row in rows])
    assert token not in dumped


@pytest.mark.asyncio
async def test_expired_revoked_and_missing_are_indistinguishable(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    assert await repo.resolve("never-issued-token-0123456789012345678901234") is None

    t_exp, _ = await repo.issue_customer_guest(
        merchant_id=merchant_one_id, shop_slug="s", ttl_seconds=-1
    )
    assert await repo.resolve(t_exp) is None

    t_rev, ctx = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")
    await repo.revoke(ctx)
    assert await repo.resolve(t_rev) is None


@pytest.mark.asyncio
async def test_resolve_returns_matching_context(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    token, issued = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s1")

    resolved = await repo.resolve(token)

    assert resolved is not None
    assert resolved.session_record_id == issued.session_record_id
    assert resolved.merchant_id == merchant_one_id
    assert resolved.shop_slug == "s1"
    assert resolved.is_bound is False


@pytest.mark.asyncio
async def test_rebinding_same_buyer_is_idempotent(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    _, ctx = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")

    a = await repo.bind_demo_customer(ctx, buyer_key="bk-1")
    b = await repo.bind_demo_customer(a, buyer_key="bk-1")

    assert a.buyer_key == b.buyer_key == "bk-1"


@pytest.mark.asyncio
async def test_rebinding_different_buyer_is_rejected(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    _, ctx = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")
    bound = await repo.bind_demo_customer(ctx, buyer_key="bk-1")

    with pytest.raises(SessionAlreadyBoundError):
        await repo.bind_demo_customer(bound, buyer_key="bk-2")


@pytest.mark.asyncio
async def test_revoking_demo_token_cascades(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    mc = MerchantContext(merchant_id=merchant_one_id)
    t1, _ = await repo.issue_merchant(mc, issuer="demo-token-A")
    t2, _ = await repo.issue_merchant(mc, issuer="demo-token-A")
    t3, _ = await repo.issue_merchant(mc, issuer="demo-token-B")

    assert await repo.revoke_by_issuer("demo-token-A") == 2
    assert await repo.resolve(t1) is None
    assert await repo.resolve(t2) is None
    assert await repo.resolve(t3) is not None


@pytest.mark.asyncio
async def test_revoke_unlisted_issuers_keeps_configured_and_customer_sessions(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """启动对账：只按指纹比较，撤销已移除 issuer 的会话，不碰顾客会话。"""

    repo = _repo(db_session)
    mc = MerchantContext(merchant_id=merchant_one_id)
    kept, _ = await repo.issue_merchant(mc, issuer="demo-token-A")
    removed_1, _ = await repo.issue_merchant(mc, issuer="demo-token-B")
    removed_2, _ = await repo.issue_merchant(mc, issuer="demo-token-C")
    guest, _ = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")

    assert await repo.revoke_unlisted_issuers({issuer_fingerprint("demo-token-A")}) == 2
    assert await repo.resolve(kept) is not None
    assert await repo.resolve(removed_1) is None
    assert await repo.resolve(removed_2) is None
    assert await repo.resolve(guest) is not None
    # 已撤销的行不重复计数，重启多次结果稳定。
    assert await repo.revoke_unlisted_issuers({issuer_fingerprint("demo-token-A")}) == 0


@pytest.mark.asyncio
async def test_revoke_unlisted_issuers_with_empty_config_revokes_all_merchant_sessions(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    repo = _repo(db_session)
    token, _ = await repo.issue_merchant(
        MerchantContext(merchant_id=merchant_one_id), issuer="demo-token-A"
    )
    guest, _ = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")

    assert await repo.revoke_unlisted_issuers(set()) == 1
    assert await repo.resolve(token) is None
    assert await repo.resolve(guest) is not None


@pytest.mark.asyncio
async def test_revoke_is_idempotent(db_session: AsyncSession, merchant_one_id: UUID) -> None:
    repo = _repo(db_session)
    _, ctx = await repo.issue_customer_guest(merchant_id=merchant_one_id, shop_slug="s")

    await repo.revoke(ctx)
    await repo.revoke(ctx)  # 第二次注销不得报错

    row = await db_session.get(AgentSession, ctx.session_record_id)
    assert row is not None
    assert row.revoked_at is not None
