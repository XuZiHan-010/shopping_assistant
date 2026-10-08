"""幂等唯一域与可信会话主体使用同一个稳定摘要。"""

from uuid import UUID

from app.core.session import SessionContext, SessionRole, principal_digest
from app.models.idempotency import IdempotencyRecord

SECRET = b"test-only-stable-principal-secret-32-bytes"
MERCHANT = UUID("00000000-0000-0000-0000-000000000100")


def _context(*, session_id: int, buyer_key: str | None) -> SessionContext:
    return SessionContext(
        session_record_id=UUID(int=session_id),
        role=SessionRole.CUSTOMER,
        merchant_id=MERCHANT,
        buyer_key=buyer_key,
        shop_slug="borough-100",
    )


def test_idempotency_uses_shared_stable_principal_digest() -> None:
    first = _context(session_id=1, buyer_key="buyer-1")
    rebound = _context(session_id=2, buyer_key="buyer-1")
    other = _context(session_id=3, buyer_key="buyer-2")
    record = IdempotencyRecord.from_session(
        first,
        secret=SECRET,
        operation="shop.orders.create",
        client_request_id="request-1",
        request_digest="a" * 64,
    )

    assert record.role == "CUSTOMER"
    assert record.merchant_id == MERCHANT
    assert record.principal_digest == principal_digest(first, secret=SECRET)
    assert record.principal_digest == principal_digest(rebound, secret=SECRET)
    assert record.principal_digest != principal_digest(other, secret=SECRET)
    assert "buyer-1" not in record.principal_digest
    assert len(record.principal_digest) == 64


def test_guest_digest_is_bound_to_session_and_merchant_digest_is_stable() -> None:
    guest_1 = _context(session_id=1, buyer_key=None)
    guest_2 = _context(session_id=2, buyer_key=None)
    assert principal_digest(guest_1, secret=SECRET) != principal_digest(guest_2, secret=SECRET)

    merchant_1 = SessionContext(UUID(int=1), SessionRole.MERCHANT, MERCHANT, None, None)
    merchant_2 = SessionContext(UUID(int=2), SessionRole.MERCHANT, MERCHANT, None, None)
    assert principal_digest(merchant_1, secret=SECRET) == principal_digest(
        merchant_2, secret=SECRET
    )
