"""N3 阶段 C Task 4：定价与促销护栏（`services/v2/guardrails.py` 新增部分）。

`check_restock` 已有的模式（预检与应用复检共用同一函数、按当时生效配置读取）原样沿用；
本文件只测新增的 `check_price_change`、`check_coupon`。
"""

from __future__ import annotations

from decimal import Decimal

from app.localization.locales import SupportedLocale
from app.services.v2.guardrails import (
    GuardrailLimits,
    check_coupon,
    check_listing_status,
    check_price_change,
)


def _limits(
    *,
    max_discount_rate: Decimal = Decimal("0.20"),
    max_price_change_rate: Decimal = Decimal("0.30"),
    min_allowed_price: Decimal | None = Decimal("10.00"),
) -> GuardrailLimits:
    return GuardrailLimits(
        max_discount_rate=max_discount_rate,
        max_price_change_rate=max_price_change_rate,
        min_allowed_price=min_allowed_price,
    )


# --- 调价护栏 -------------------------------------------------------------------------


def test_price_change_blocked_when_min_price_unconfigured() -> None:
    """M6：没有配置最低允许售价时，任何调价都不放行应用。"""

    limits = _limits(min_allowed_price=None)
    checks = check_price_change(
        current_price=Decimal("100.00"), new_price=Decimal("99.00"), limits=limits
    )
    assert any(not check.passed for check in checks)


def test_price_change_blocked_below_min_allowed_price() -> None:
    limits = _limits(min_allowed_price=Decimal("50.00"))
    checks = check_price_change(
        current_price=Decimal("100.00"), new_price=Decimal("40.00"), limits=limits
    )
    assert any(not check.passed for check in checks)


def test_price_change_blocked_over_max_change_rate() -> None:
    """单次调价幅度上限：从 100 降到 50 是 50% 降幅，超过 30% 上限。"""

    limits = _limits(max_price_change_rate=Decimal("0.30"), min_allowed_price=Decimal("10.00"))
    checks = check_price_change(
        current_price=Decimal("100.00"), new_price=Decimal("50.00"), limits=limits
    )
    assert any(not check.passed for check in checks)


def test_price_change_within_limits_passes() -> None:
    limits = _limits(max_price_change_rate=Decimal("0.30"), min_allowed_price=Decimal("10.00"))
    checks = check_price_change(
        current_price=Decimal("100.00"), new_price=Decimal("85.00"), limits=limits
    )
    assert all(check.passed for check in checks)


def test_price_increase_is_not_subject_to_min_price_floor() -> None:
    """涨价不应被最低售价规则拦下——该规则只保护"不能卖得比底线低"。"""

    limits = _limits(min_allowed_price=Decimal("50.00"), max_price_change_rate=Decimal("0.30"))
    checks = check_price_change(
        current_price=Decimal("100.00"), new_price=Decimal("120.00"), limits=limits
    )
    assert all(check.passed for check in checks)


# --- 促销/券护栏 ----------------------------------------------------------------------


def test_coupon_blocked_over_20_percent_discount() -> None:
    """Q6：实付不得低于原价 80%，即减免比例不得超过 20%。"""

    limits = _limits(max_discount_rate=Decimal("0.20"))
    checks = check_coupon(discount_rate=Decimal("0.25"), limits=limits)
    assert any(not check.passed for check in checks)


def test_coupon_at_exactly_20_percent_passes() -> None:
    limits = _limits(max_discount_rate=Decimal("0.20"))
    checks = check_coupon(discount_rate=Decimal("0.20"), limits=limits)
    assert all(check.passed for check in checks)


def test_full_reduction_coupon_over_20_percent_is_blocked() -> None:
    checks = check_coupon(
        threshold_amount=Decimal("100.00"),
        discount_amount=Decimal("25.00"),
        limits=_limits(),
    )
    failed = [check for check in checks if not check.passed]
    assert len(failed) == 1
    assert failed[0].code == "DISCOUNT_RATE_EXCEEDS_LIMIT"
    assert failed[0].current_limit and failed[0].remediation


def test_full_reduction_coupon_at_limit_passes_and_zero_threshold_fails() -> None:
    assert all(
        check.passed
        for check in check_coupon(
            threshold_amount=Decimal("100.00"),
            discount_amount=Decimal("20.00"),
            limits=_limits(),
        )
    )
    assert any(
        not check.passed
        for check in check_coupon(
            threshold_amount=Decimal("0.00"),
            discount_amount=Decimal("1.00"),
            limits=_limits(),
        )
    )


def test_coupon_guardrail_tightened_after_drafting_is_enforced_at_apply() -> None:
    """起草时用旧配置通过，应用时护栏收紧后必须按当时生效配置复检（D9②）。"""

    drafted_limits = _limits(max_discount_rate=Decimal("0.20"))
    assert all(
        check.passed for check in check_coupon(discount_rate=Decimal("0.15"), limits=drafted_limits)
    )
    tightened_limits = _limits(max_discount_rate=Decimal("0.10"))
    assert any(
        not check.passed
        for check in check_coupon(discount_rate=Decimal("0.15"), limits=tightened_limits)
    )


def test_guardrail_failure_always_carries_limit_and_remediation() -> None:
    limits = _limits(min_allowed_price=None)
    checks = check_price_change(
        current_price=Decimal("100.00"), new_price=Decimal("99.00"), limits=limits
    )
    failed = [check for check in checks if not check.passed]
    assert failed
    for check in failed:
        assert check.current_limit is not None
        assert check.remediation is not None


def test_guardrail_texts_localized_for_english() -> None:
    limits = _limits(min_allowed_price=None)
    checks = check_price_change(
        current_price=Decimal("100.00"),
        new_price=Decimal("99.00"),
        limits=limits,
        locale=SupportedLocale.EN_US,
    )
    failed = next(check for check in checks if not check.passed)
    assert failed.current_limit is not None
    assert all(ord(ch) < 128 for ch in failed.current_limit)


# --- 上下架护栏 -----------------------------------------------------------------------


def test_pause_requires_online_product() -> None:
    [check] = check_listing_status(action="PAUSE", current_status="ONLINE")
    assert check.passed and check.code == "LISTING_STATUS_NOT_TOGGLEABLE"


def test_activate_requires_offline_product() -> None:
    [check] = check_listing_status(action="ACTIVATE", current_status="OFFLINE")
    assert check.passed


def test_listing_status_rejects_every_other_combination_with_bilingual_reason() -> None:
    for action, status in [
        ("PAUSE", "OFFLINE"),
        ("PAUSE", "AUDITING"),
        ("PAUSE", "REJECTED"),
        ("ACTIVATE", "ONLINE"),
        ("ACTIVATE", "AUDITING"),
        ("ACTIVATE", "REJECTED"),
    ]:
        zh = check_listing_status(action=action, current_status=status)[0]
        en = check_listing_status(
            action=action, current_status=status, locale=SupportedLocale.EN_US
        )[0]
        assert not zh.passed and zh.code == "LISTING_STATUS_NOT_TOGGLEABLE"
        assert zh.current_limit and zh.remediation and status in zh.current_limit
        assert en.current_limit and en.remediation
        assert en.current_limit != zh.current_limit
        assert not any("一" <= ch <= "鿿" for ch in en.current_limit + en.remediation)
