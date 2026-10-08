"""结账时的券额分摊（交易计划 Task 3，契约 §8.7.8 舍入顺序）。

必须复用券展示的同一个换算：顾客在券列表看到「9 折」，结账就按 9000 bps 付款。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.services.v2.coupons import CouponNotApplicableError, CouponRow, allocate_discounts

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


def _percent(rate: str, **overrides: object) -> CouponRow:
    return _row(
        kind="DISCOUNT",
        discount_amount=None,
        discount_rate=Decimal(rate),
        threshold_amount=None,
        **overrides,
    )


def test_amount_off_is_split_by_line_share_and_sums_exactly() -> None:
    discounts = allocate_discounts(_row(), [("a", 10000), ("b", 20000)], now=NOW)

    assert discounts == [333, 667]
    assert sum(discounts) == 1000


def test_amount_off_leftover_cents_go_to_the_largest_remainders() -> None:
    discounts = allocate_discounts(
        _row(threshold_amount=None, discount_amount=Decimal("1.00")),
        [("a", 100), ("b", 100), ("c", 100)],
        now=NOW,
    )

    assert discounts == [34, 33, 33]


def test_amount_off_never_exceeds_the_eligible_gross() -> None:
    discounts = allocate_discounts(
        _row(threshold_amount=None, discount_amount=Decimal("50.00")), [("a", 300)], now=NOW
    )

    assert discounts == [300]


def test_percent_off_rounds_each_line_half_up_before_summing() -> None:
    """9 折：行 99.99 元 → 实付 89.991 → 89.99；行 0.05 元 → 实付 0.045 → 0.05（HALF_UP）。"""

    discounts = allocate_discounts(_percent("0.10"), [("a", 9999), ("b", 5)], now=NOW)

    assert discounts == [1000, 0]


def test_percent_off_uses_the_same_direction_as_the_coupon_list() -> None:
    """库里 0.20 是减免比例：100 元实付 80 元，而不是 20 元。"""

    assert allocate_discounts(_percent("0.20"), [("a", 10000)], now=NOW) == [2000]


def test_product_scoped_coupon_only_discounts_its_products() -> None:
    discounts = allocate_discounts(
        _row(threshold_amount=None, product_ids=["b"]), [("a", 10000), ("b", 5000)], now=NOW
    )

    assert discounts == [0, 1000]


def test_threshold_counts_only_eligible_lines() -> None:
    with pytest.raises(CouponNotApplicableError):
        allocate_discounts(_row(product_ids=["b"]), [("a", 50000), ("b", 5000)], now=NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"state": "DISABLED"},
        {"starts_at": NOW + timedelta(hours=1)},
        {"ends_at": NOW},
        {"product_ids": ["zzz"]},
        {"discount_amount": None},
    ],
)
def test_unusable_coupons_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(CouponNotApplicableError):
        allocate_discounts(_row(threshold_amount=None, **overrides), [("a", 10000)], now=NOW)


def test_threshold_not_met_is_rejected() -> None:
    with pytest.raises(CouponNotApplicableError):
        allocate_discounts(_row(), [("a", 9999)], now=NOW)
