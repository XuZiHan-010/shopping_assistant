"""券的库内表示到契约 `CouponSummary`（§8.8.1）的唯一换算点。

两处方向相反、最容易写错：

- 库里的 `discount_rate` 是**减免比例**（PRD M6：「最大优惠幅度 20%，即实付不得低于原价 80%」，
  护栏 `max_discount_rate ≤ 0.20` 同样按减免计）；
- 契约的 `discount_bps` 是**折扣后的支付比例**（基点）。

结账（交易计划 Task 3）重算券额时必须复用本模块，不得另写一套换算。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from app.schemas.v2.common import yuan_to_cents
from app.schemas.v2.shop_session import CouponSummary

#: 只有明确处于该状态的券才展示；未知状态按故障关闭处理，宁可漏展示也不误展示。
ACTIVE_STATE: Final = "ACTIVE"
_KIND_TO_CONTRACT: Final = {"FULL_REDUCTION": "AMOUNT_OFF", "DISCOUNT": "PERCENT_OFF"}
_BPS: Final = Decimal(10000)


@dataclass(frozen=True)
class CouponRow:
    id: str
    name: str
    kind: str
    threshold_amount: Decimal | None
    discount_amount: Decimal | None
    discount_rate: Decimal | None
    product_ids: list[str]
    starts_at: datetime
    ends_at: datetime
    state: str
    #: 只用于列表排序与游标，不进入对外模型。
    created_at: datetime


def payment_bps(discount_rate: Decimal) -> int:
    """减免比例 → 支付比例基点：减 10% 即按 9000 bps 支付。"""

    return int(((Decimal(1) - discount_rate) * _BPS).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def is_active(row: CouponRow, *, now: datetime) -> bool:
    """契约 §8.8.2：仅当前已生效券，`starts_at ≤ now < ends_at` 且未停用。"""

    return row.state == ACTIVE_STATE and row.starts_at <= now < row.ends_at


def to_coupon_summary(row: CouponRow) -> CouponSummary:
    percent = row.kind == "DISCOUNT"
    return CouponSummary(
        id=row.id,
        name=row.name,
        kind=_KIND_TO_CONTRACT[row.kind],
        min_spend_cents=yuan_to_cents(row.threshold_amount or Decimal("0")),
        amount_off_cents=(
            None if percent or row.discount_amount is None else yuan_to_cents(row.discount_amount)
        ),
        discount_bps=(
            payment_bps(row.discount_rate) if percent and row.discount_rate is not None else None
        ),
        product_ids=list(row.product_ids),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
    )


class CouponNotApplicableError(ValueError):
    """券对这张订单不可用：未生效 / 已停用 / 未达门槛 / 没有适用商品 / 券面数据不完整。"""


def allocate_discounts(
    row: CouponRow, lines: Sequence[tuple[str, int]], *, now: datetime
) -> list[int]:
    """把券额分摊到订单行，返回与 `lines` 一一对应的行优惠（分）。

    `lines` 是 `(product_id, 行原价分)`。舍入顺序按契约 §8.7.8「先逐行舍入到分，再求和」：

    - 折扣券：每行 `实付 = ROUND_HALF_UP(行原价 × 支付比例)`，行优惠 = 行原价 − 实付；
      支付比例与券列表展示共用 `payment_bps`，顾客看到的折扣与实际扣款不会对不上；
    - 满减券：券额（不超过适用行原价之和）按行原价比例分摊，取整用最大余数法——
      总额必须恰好等于券额，逐行独立四舍五入会多扣或少扣一分。
    """

    if not is_active(row, now=now):
        raise CouponNotApplicableError("券未生效或已停用")
    eligible = [
        index
        for index, (product_id, _) in enumerate(lines)
        if not row.product_ids or product_id in row.product_ids
    ]
    base = sum(lines[index][1] for index in eligible)
    threshold = yuan_to_cents(row.threshold_amount or Decimal("0"))
    if not eligible or base <= 0 or base < threshold:
        raise CouponNotApplicableError("未达使用门槛或没有适用商品")

    discounts = [0] * len(lines)
    if row.kind == "DISCOUNT":
        if row.discount_rate is None:
            raise CouponNotApplicableError("折扣券缺少折扣比例")
        bps = Decimal(payment_bps(row.discount_rate))
        for index in eligible:
            gross = lines[index][1]
            paid = int((Decimal(gross) * bps / _BPS).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            discounts[index] = gross - paid
        return discounts

    if row.kind != "FULL_REDUCTION" or row.discount_amount is None:
        raise CouponNotApplicableError("满减券缺少减免金额")
    total = min(yuan_to_cents(row.discount_amount), base)
    shares = [(index, total * lines[index][1]) for index in eligible]
    for index, weighted in shares:
        discounts[index] = weighted // base
    leftover = total - sum(discounts)
    # 余数按「被截掉的部分」从大到小逐分补回；同余时先补靠前的行，结果确定。
    by_remainder = sorted(shares, key=lambda item: (-(item[1] % base), item[0]))
    for index, _ in by_remainder[:leftover]:
        discounts[index] += 1
    return discounts
