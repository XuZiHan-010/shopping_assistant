"""演示数据生成。

不碰数据库：Seed 的正确性（覆盖天数、退款退货的组合样本、商家隔离）必须能在
没有 PostgreSQL 的机器上验证，否则这些性质只能靠人工翻库确认。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.analytics.demo_data import (
    DEMO_ANALYTICS_SEED_BASE,
    DemoDataset,
    build_demo_dataset,
)

MERCHANT = UUID("00000000-0000-0000-0000-000000000001")
END = date(2026, 8, 4)


def _dataset():
    return build_demo_dataset(
        merchant_id=MERCHANT, end_date=END, days=180, seed=DEMO_ANALYTICS_SEED_BASE
    )


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


def test_a_business_day_is_identical_regardless_of_generation_window() -> None:
    """演示数据每天滚动，但历史必须钉死。

    否则今天回答里的「8月17日退货 15 件」明天会变成别的数字，已落库的 answers
    与会话历史全部对不上——这正是「每日全量重建」方案的致命缺陷。
    """

    target = date(2026, 8, 3)
    wide = build_demo_dataset(merchant_id=MERCHANT, end_date=END, days=180, seed=1)
    narrow = build_demo_dataset(merchant_id=MERCHANT, end_date=target, days=7, seed=1)

    def facts_on(dataset: DemoDataset) -> tuple[object, ...]:
        return tuple(
            tuple(row for row in rows if row["business_date"] == target)
            for rows in (
                dataset.orders,
                dataset.order_items,
                dataset.refunds,
                dataset.returns,
                dataset.tickets,
            )
        )

    assert facts_on(wide) == facts_on(narrow)
    assert wide.products == narrow.products
    codes = {(row["merchant_id"], row["product_code"]) for row in wide.products}
    assert len(codes) == len(wide.products), "商品目录受 UNIQUE(merchant_id, product_code) 约束"


def test_the_rolling_job_and_the_full_rebuild_script_share_one_random_baseline() -> None:
    """两个写入口用不同 seed，会让新旧两段历史落在两条随机序列上，交界处出现断层。"""

    import importlib.util
    from pathlib import Path

    from app.jobs.seed_demo_rolling import DEMO_ANALYTICS_SEED_BASE as rolling_base

    # 按文件路径加载：仓库根与 backend/ 下各有一个顶层 `scripts` 包，
    # 全量跑测试时 `import scripts.seed_demo_analytics` 会解析到另一个包。
    path = Path(__file__).resolve().parents[3] / "scripts" / "seed_demo_analytics.py"
    spec = importlib.util.spec_from_file_location("seed_demo_analytics_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert rolling_base == DEMO_ANALYTICS_SEED_BASE
    assert module.DEMO_ANALYTICS_SEED_BASE == DEMO_ANALYTICS_SEED_BASE
    assert DEMO_ANALYTICS_SEED_BASE == 20260804


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
