"""退款使用订单行快照并逐行限制累计金额。"""

from decimal import Decimal

import pytest

from app.services.v2.refund_calc import RefundLine, refundable, total_refundable


def test_line_cap_includes_previous_refunds() -> None:
    line = RefundLine(line_total=Decimal("253.00"), previously_refunded=Decimal("120.00"))
    assert refundable(line) == Decimal("133.00")


def test_each_line_rounds_before_sum() -> None:
    lines = [RefundLine(line_total=Decimal("0.014")) for _ in range(3)]
    assert total_refundable(lines) == Decimal("0.03")


def test_refund_cannot_exceed_snapshot_or_use_float() -> None:
    with pytest.raises(ValueError):
        refundable(RefundLine(line_total=Decimal("10.00"), previously_refunded=Decimal("10.01")))
    with pytest.raises(ValueError):
        refundable(RefundLine(line_total=10.0))  # type: ignore[arg-type]


def test_negative_or_nonfinite_amount_is_rejected() -> None:
    for amount in (Decimal("-0.01"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError):
            refundable(RefundLine(line_total=amount))
