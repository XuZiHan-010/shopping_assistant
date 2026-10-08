"""券的库内表示 → 契约 `CouponSummary`（§8.8.1）。

库里的 `discount_rate` 是**减免比例**（PRD M6：最大优惠幅度 20%，即实付不低于原价 80%），
契约的 `discount_bps` 是**折扣后的支付比例**。两者方向相反，换算只在这一处。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.services.v2.coupons import CouponRow, is_active, payment_bps, to_coupon_summary

NOW = datetime(2026, 9, 23, 12, tzinfo=UTC)


def _row(**overrides: object) -> CouponRow:
    values: dict[str, object] = {
        "id": "c-1",
        "name": "满 100 减 10",
        "kind": "FULL_REDUCTION",
        "threshold_amount": Decimal("100.00"),
        "discount_amount": Decimal("10.00"),
        "discount_rate": None,
        "product_ids": [],
        "starts_at": NOW - timedelta(days=1),
        "ends_at": NOW + timedelta(days=1),
        "state": "ACTIVE",
        "created_at": NOW - timedelta(days=2),
    }
    values.update(overrides)
    return CouponRow(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("rate", "expected"),
    [(Decimal("0.10"), 9000), (Decimal("0.20"), 8000), (Decimal("0.0850"), 9150)],
)
def test_payment_bps_is_the_complement_of_the_stored_reduction(
    rate: Decimal, expected: int
) -> None:
    assert payment_bps(rate) == expected


def test_full_reduction_maps_to_amount_off_in_cents() -> None:
    summary = to_coupon_summary(_row())

    assert summary.kind == "AMOUNT_OFF"
    assert summary.min_spend_cents == 10000
    assert summary.amount_off_cents == 1000
    assert summary.discount_bps is None


def test_discount_maps_to_percent_off_with_payment_ratio() -> None:
    summary = to_coupon_summary(
        _row(kind="DISCOUNT", discount_amount=None, discount_rate=Decimal("0.15"))
    )

    assert summary.kind == "PERCENT_OFF"
    assert summary.amount_off_cents is None
    assert summary.discount_bps == 8500


def test_missing_threshold_means_no_minimum_spend() -> None:
    assert to_coupon_summary(_row(threshold_amount=None)).min_spend_cents == 0


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, True),
        ({"starts_at": NOW}, True),
        ({"ends_at": NOW}, False),
        ({"starts_at": NOW + timedelta(seconds=1)}, False),
        ({"state": "DISABLED"}, False),
        ({"state": "SOMETHING_ELSE"}, False),
    ],
)
def test_only_active_coupons_inside_their_window_are_live(
    overrides: dict[str, object], expected: bool
) -> None:
    assert is_active(_row(**overrides), now=NOW) is expected
