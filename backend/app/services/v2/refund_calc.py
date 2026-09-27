"""按订单行价格快照计算退款。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class RefundLine:
    line_total: Decimal
    previously_refunded: Decimal = Decimal("0")


def refundable(line: RefundLine) -> Decimal:
    """可退余额包含此前退款，并确保累计不超过此行快照。"""

    total = line.line_total
    refunded = line.previously_refunded
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in (total, refunded)):
        raise ValueError("退款金额必须是有限 Decimal 元")
    if total < 0 or refunded < 0 or refunded > total:
        raise ValueError("累计退款不能超过非负的订单行实付快照")
    return (total - refunded).quantize(_CENT, rounding=ROUND_HALF_UP)


def total_refundable(lines: Iterable[RefundLine]) -> Decimal:
    """先逐行舍入到分，再求和；金额不经过浮点数。"""

    return sum((refundable(line) for line in lines), Decimal("0.00"))
