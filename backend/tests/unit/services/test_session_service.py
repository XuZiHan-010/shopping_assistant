"""`SessionService` 编排逻辑：不触达真实数据库，用 Fake 仓储隔离测试。"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.core.errors import ResourceForbiddenError, ResourceNotFoundError
from app.core.security import MerchantContext
from app.core.session import SessionContext, SessionRole
from app.services.session_service import SessionService

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000100")


class _FakeMerchantRepository:
    def __init__(self, slugs: dict[str, UUID]) -> None:
        self._slugs = slugs

    async def get_active_by_shop_slug(self, shop_slug: str) -> UUID | None:
        return self._slugs.get(shop_slug)


class _FakeSessionRepository:
    def __init__(self) -> None:
        self.issued_guest_calls: list[tuple[UUID, str]] = []
        self.bind_calls: list[tuple[UUID, str]] = []
        self._bound: dict[UUID, str] = {}

    async def issue_customer_guest(
        self, *, merchant_id: UUID, shop_slug: str, ttl_seconds: int | None = None
    ) -> tuple[str, SessionContext]:
        self.issued_guest_calls.append((merchant_id, shop_slug))
        record_id = uuid4()
        return "guest-token", SessionContext(
            session_record_id=record_id,
            role=SessionRole.CUSTOMER,
            merchant_id=merchant_id,
            buyer_key=None,
            shop_slug=shop_slug,
        )

    async def bind_demo_customer(self, ctx: SessionContext, *, buyer_key: str) -> SessionContext:
        self.bind_calls.append((ctx.session_record_id, buyer_key))
        self._bound[ctx.session_record_id] = buyer_key
        return SessionContext(
            session_record_id=ctx.session_record_id,
            role=ctx.role,
            merchant_id=ctx.merchant_id,
            buyer_key=buyer_key,
            shop_slug=ctx.shop_slug,
        )

    async def bind_demo_customer_once(self, ctx: SessionContext, *, buyer_key: str):
        from app.core.session import SessionAlreadyBoundError

        existing = self._bound.get(ctx.session_record_id, ctx.buyer_key)
        if existing is not None and existing != buyer_key:
            raise SessionAlreadyBoundError
        return await self.bind_demo_customer(ctx, buyer_key=buyer_key), existing is None

    async def issue_merchant(
        self, mc: MerchantContext, *, issuer: str, ttl_seconds: int | None = None
    ) -> tuple[str, SessionContext]:
        record_id = uuid4()
        return "merchant-token", SessionContext(
            session_record_id=record_id,
            role=SessionRole.MERCHANT,
            merchant_id=mc.merchant_id,
            buyer_key=None,
            shop_slug=None,
        )


class _FakeCartMerge:
    def __init__(self, *, adjusted: bool = False) -> None:
        self.calls: list[tuple[UUID, str, UUID]] = []
        self._adjusted = adjusted

    async def merge_guest_into_buyer(
        self, *, session, merchant_id: UUID, buyer_key: str, guest_session_id: UUID
    ) -> bool:
        self.calls.append((merchant_id, buyer_key, guest_session_id))
        return self._adjusted


def _service(
    *,
    merchants: _FakeMerchantRepository,
    sessions: _FakeSessionRepository,
    cart_merge: _FakeCartMerge,
    demo_customer_identities: dict[str, str] | None = None,
) -> SessionService:
    return SessionService(
        session=object(),  # 编排逻辑不直接使用 session，只透传给 cart_merge
        merchants=merchants,  # type: ignore[arg-type]
        sessions=sessions,  # type: ignore[arg-type]
        cart_merge=cart_merge,  # type: ignore[arg-type]
        demo_customer_identities=demo_customer_identities or {},
    )


@pytest.mark.asyncio
async def test_create_guest_resolves_shop_slug_to_merchant() -> None:
    sessions = _FakeSessionRepository()
    service = _service(
        merchants=_FakeMerchantRepository({"borough-100": MERCHANT_ID}),
        sessions=sessions,
        cart_merge=_FakeCartMerge(),
    )

    token, ctx = await service.create_guest("borough-100")

    assert token == "guest-token"
    assert ctx.merchant_id == MERCHANT_ID
    assert sessions.issued_guest_calls == [(MERCHANT_ID, "borough-100")]


@pytest.mark.asyncio
async def test_create_guest_rejects_unknown_shop_slug_without_creating_session() -> None:
    sessions = _FakeSessionRepository()
    service = _service(
        merchants=_FakeMerchantRepository({}),
        sessions=sessions,
        cart_merge=_FakeCartMerge(),
    )

    with pytest.raises(ResourceForbiddenError):
        await service.create_guest("unknown-shop")

    assert sessions.issued_guest_calls == []


@pytest.mark.asyncio
async def test_bind_demo_customer_rejects_shop_without_configured_identity() -> None:
    sessions = _FakeSessionRepository()
    ctx = SessionContext(
        session_record_id=uuid4(),
        role=SessionRole.CUSTOMER,
        merchant_id=MERCHANT_ID,
        buyer_key=None,
        shop_slug="borough-100",
    )
    service = _service(
        merchants=_FakeMerchantRepository({}),
        sessions=sessions,
        cart_merge=_FakeCartMerge(),
        demo_customer_identities={},
    )

    with pytest.raises(ResourceNotFoundError):
        await service.bind_demo_customer(ctx)

    assert sessions.bind_calls == []


@pytest.mark.asyncio
async def test_bind_demo_customer_merges_cart_only_on_first_bind() -> None:
    sessions = _FakeSessionRepository()
    cart_merge = _FakeCartMerge(adjusted=True)
    guest_ctx = SessionContext(
        session_record_id=uuid4(),
        role=SessionRole.CUSTOMER,
        merchant_id=MERCHANT_ID,
        buyer_key=None,
        shop_slug="borough-100",
    )
    service = _service(
        merchants=_FakeMerchantRepository({}),
        sessions=sessions,
        cart_merge=cart_merge,
        demo_customer_identities={"borough-100": "demo-buyer-1"},
    )

    bound, cart_adjusted = await service.bind_demo_customer(guest_ctx)

    assert bound.buyer_key == "demo-buyer-1"
    assert cart_adjusted is True
    assert len(cart_merge.calls) == 1


@pytest.mark.asyncio
async def test_bind_demo_customer_skips_cart_merge_when_already_bound() -> None:
    sessions = _FakeSessionRepository()
    cart_merge = _FakeCartMerge(adjusted=True)
    bound_ctx = SessionContext(
        session_record_id=uuid4(),
        role=SessionRole.CUSTOMER,
        merchant_id=MERCHANT_ID,
        buyer_key="demo-buyer-1",
        shop_slug="borough-100",
    )
    service = _service(
        merchants=_FakeMerchantRepository({}),
        sessions=sessions,
        cart_merge=cart_merge,
        demo_customer_identities={"borough-100": "demo-buyer-1"},
    )

    bound, cart_adjusted = await service.bind_demo_customer(bound_ctx)

    assert bound.buyer_key == "demo-buyer-1"
    assert cart_adjusted is False
    assert cart_merge.calls == []


@pytest.mark.asyncio
async def test_issue_merchant_delegates_to_repository() -> None:
    sessions = _FakeSessionRepository()
    service = _service(
        merchants=_FakeMerchantRepository({}),
        sessions=sessions,
        cart_merge=_FakeCartMerge(),
    )
    mc = MerchantContext(merchant_id=MERCHANT_ID)

    token, ctx = await service.issue_merchant(mc, issuer="demo-token-A")

    assert token == "merchant-token"
    assert ctx.role is SessionRole.MERCHANT
    assert ctx.merchant_id == MERCHANT_ID


@pytest.mark.asyncio
async def test_stale_guest_context_does_not_merge_twice() -> None:
    sessions = _FakeSessionRepository()
    cart = _FakeCartMerge()
    service = _service(
        merchants=_FakeMerchantRepository({}),
        sessions=sessions,
        cart_merge=cart,
        demo_customer_identities={"s": "buyer"},
    )
    _, guest = await sessions.issue_customer_guest(merchant_id=MERCHANT_ID, shop_slug="s")
    await service.bind_demo_customer(guest)
    await service.bind_demo_customer(guest)
    assert len(cart.calls) == 1
