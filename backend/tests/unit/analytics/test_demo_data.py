"""演示数据生成。

不碰数据库：Seed 的正确性（覆盖天数、退款退货的组合样本、商家隔离）必须能在
没有 PostgreSQL 的机器上验证，否则这些性质只能靠人工翻库确认。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.analytics.demo_data import build_demo_dataset

MERCHANT = UUID("00000000-0000-0000-0000-000000000001")
END = date(2026, 8, 4)


def _dataset():
    return build_demo_dataset(merchant_id=MERCHANT, end_date=END, days=180, seed=20260804)


def test_orders_cover_exactly_the_requested_window() -> None:
    dataset = _dataset()

    dates = {row["business_date"] for row in dataset.orders}

    assert min(dates) == date(2026, 2, 6)
    assert max(dates) == END
    assert len(dates) == 180


def test_generation_is_deterministic_for_the_same_seed() -> None:
    """演示数据不确定，就没法复现「昨天 GMV 是多少」这类断言。"""

    first = build_demo_dataset(merchant_id=MERCHANT, end_date=END, days=180, seed=1)
    second = build_demo_dataset(merchant_id=MERCHANT, end_date=END, days=180, seed=1)

    assert first.orders == second.orders
    assert first.returns == second.returns


def test_every_row_carries_the_requested_merchant() -> None:
    dataset = _dataset()

    for rows in (
        dataset.products,
        dataset.orders,
        dataset.order_items,
        dataset.refunds,
        dataset.returns,
        dataset.tickets,
    ):
        assert rows
        assert {row["merchant_id"] for row in rows} == {MERCHANT}


def test_dataset_contains_refund_only_and_refund_with_return_samples() -> None:
    """PRD 要求退款与退货各自成域：只有两种样本同时存在，才能验证二者不混淆。"""

    dataset = _dataset()
    refunded_items = {row["order_item_id"] for row in dataset.refunds}
    returned_items = {row["order_item_id"] for row in dataset.returns}

    assert refunded_items - returned_items, "缺少「只退款不退货」样本"
    assert refunded_items & returned_items, "缺少「退货并退款」样本"
    assert returned_items - refunded_items, "缺少「只退货不退款」样本"


def test_order_item_business_date_follows_the_order_not_the_refund() -> None:
    """退货率的分母按下单日归属；订单项的业务日跟着订单走。"""

    dataset = _dataset()
    order_dates = {row["id"]: row["business_date"] for row in dataset.orders}

    for item in dataset.order_items:
        assert item["business_date"] == order_dates[item["order_id"]]


def test_money_values_are_decimal_not_float() -> None:
    dataset = _dataset()

    assert all(isinstance(row["paid_amount"], Decimal) for row in dataset.orders)
    assert all(isinstance(row["refund_amount"], Decimal) for row in dataset.refunds)


def test_paid_orders_have_a_paid_at_and_cancelled_ones_do_not() -> None:
    dataset = _dataset()

    for order in dataset.orders:
        if order["order_status"] in {"PAID", "SHIPPED", "COMPLETED"}:
            assert order["paid_at"] is not None
        if order["order_status"] == "CANCELLED":
            assert order["paid_at"] is None
            assert order["paid_amount"] == Decimal("0.00")
