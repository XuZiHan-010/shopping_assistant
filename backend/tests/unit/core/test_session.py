import re
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from app.core.session import (
    SessionContext,
    SessionRole,
    buyer_alias,
    issuer_fingerprint,
    new_session_token,
    token_fingerprint,
)

MID = UUID("00000000-0000-0000-0000-000000000100")
MID_A = UUID("00000000-0000-0000-0000-000000000101")
MID_B = UUID("00000000-0000-0000-0000-000000000102")
ALIAS_KEY = b"test-only-buyer-alias-key-32-bytes"


def test_token_is_high_entropy_and_urlsafe() -> None:
    """降低随机字节数或改用非 URL 安全编码时应失败。"""
    token = new_session_token()

    assert len(token) >= 43
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)


def test_tokens_are_unique() -> None:
    """将令牌替换为固定值或低熵值时应失败。"""
    assert len({new_session_token() for _ in range(1_000)}) == 1_000


def test_fingerprint_is_stable_and_irreversible() -> None:
    """移除哈希或截断摘要时应失败。"""
    token = new_session_token()

    assert token_fingerprint(token) == token_fingerprint(token)
    assert token not in token_fingerprint(token)
    assert len(token_fingerprint(token)) == 64


def test_issuer_fingerprint_is_stable_and_does_not_leak_token() -> None:
    """将签发来源保存为明文或改为短摘要时应失败。"""
    demo_token = "test-only-merchant-login-token"

    assert issuer_fingerprint(demo_token) == issuer_fingerprint(demo_token)
    assert demo_token not in issuer_fingerprint(demo_token)
    assert len(issuer_fingerprint(demo_token)) == 64


def test_customer_context_requires_buyer_key_only_when_bound() -> None:
    """错误地把访客视为已绑定时应失败。"""
    guest = SessionContext(
        session_record_id=UUID(int=1),
        role=SessionRole.CUSTOMER,
        merchant_id=MID,
        buyer_key=None,
        shop_slug="borough-100",
    )
    bound = SessionContext(
        session_record_id=UUID(int=1),
        role=SessionRole.CUSTOMER,
        merchant_id=MID,
        buyer_key="bk-1",
        shop_slug="borough-100",
    )

    assert guest.is_bound is False
    assert bound.is_bound is True


def test_merchant_context_must_not_carry_buyer_key() -> None:
    """允许商家会话携带顾客主体时应失败。"""
    with pytest.raises(ValueError):
        SessionContext(
            session_record_id=UUID(int=1),
            role=SessionRole.MERCHANT,
            merchant_id=MID,
            buyer_key="bk-1",
            shop_slug=None,
        )


def test_context_is_frozen() -> None:
    """允许角色在构造后变更时应失败。"""
    context = SessionContext(
        session_record_id=UUID(int=1),
        role=SessionRole.MERCHANT,
        merchant_id=MID,
        buyer_key=None,
        shop_slug=None,
    )

    with pytest.raises(FrozenInstanceError):
        context.role = SessionRole.CUSTOMER  # type: ignore[misc]


def test_buyer_alias_is_stable_per_merchant() -> None:
    """别名派生中引入随机性时应失败。"""
    assert buyer_alias(ALIAS_KEY, MID_A, "bk-1") == buyer_alias(ALIAS_KEY, MID_A, "bk-1")


def test_buyer_alias_is_not_cross_linkable_between_merchants() -> None:
    """移除商家范围派生时应失败。"""
    assert buyer_alias(ALIAS_KEY, MID_A, "bk-1") != buyer_alias(ALIAS_KEY, MID_B, "bk-1")


def test_buyer_alias_does_not_leak_buyer_key() -> None:
    """将原始 buyer_key 直接放进展示别名时应失败。"""
    alias = buyer_alias(ALIAS_KEY, MID_A, "bk-1")

    assert "bk-1" not in alias
    assert len(alias) <= 16


def test_string_role_is_coerced_so_merchant_guard_still_applies() -> None:
    """角色以字符串传入时，商家不得携带 buyer_key 的守卫不能被绕过。"""
    with pytest.raises(ValueError):
        SessionContext(
            session_record_id=UUID("00000000-0000-0000-0000-0000000000aa"),
            role="MERCHANT",  # type: ignore[arg-type]
            merchant_id=MID,
            buyer_key="bk-1",
            shop_slug=None,
        )
    with pytest.raises(ValueError):
        SessionContext(
            session_record_id=UUID("00000000-0000-0000-0000-0000000000aa"),
            role="ADMIN",  # type: ignore[arg-type]
            merchant_id=MID,
            buyer_key=None,
            shop_slug=None,
        )


def test_buyer_alias_follows_display_locale_and_stays_short() -> None:
    from app.localization.locales import SupportedLocale

    zh = buyer_alias(ALIAS_KEY, MID_A, "bk-1")
    en = buyer_alias(ALIAS_KEY, MID_A, "bk-1", SupportedLocale.EN_US)

    assert zh.startswith("顾客 #") and en.startswith("Buyer #")
    assert zh.split("#")[1] == en.split("#")[1]
    assert len(en) <= 16
