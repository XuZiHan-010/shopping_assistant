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


def test_storefront_catalog_matches_approved_products_and_gaps() -> None:
    from app.analytics.demo_data import build_demo_catalog
    from app.services.v2.content_completeness import required_attributes_for

    products = build_demo_catalog(merchant_id=MERCHANT, seed=DEMO_ANALYTICS_SEED_BASE)
    expected = [
        ("真丝印花半裙", 569),
        ("牛津纺长袖衬衫", 239),
        ("手工缝线切尔西靴", 699),
        ("粗陶手作咖啡杯（两只装）", 128),
        ("燕麦舒缓保湿面霜", 159),
        ("亚麻宽松开衫", 329),
        ("水洗帆布工装夹克", 459),
        ("复古德训运动鞋", 389),
        ("橡木砧板", 199),
        ("玫瑰果油修护精华", 219),
        ("羊毛混纺高领毛衣", 399),
        ("美利奴羊毛针织开衫", 529),
        ("软底乐福鞋", 459),
        ("亚麻格纹桌布", 169),
        ("苦橙花淡香水", 399),
        ("高腰直筒牛仔裤", 299),
        ("格纹羊绒围巾", 489),
        ("防泼水徒步短靴", 629),
        ("无花果雪松香氛蜡烛", 149),
        ("氨基酸温和洁面乳", 89),
        ("法式碎花连衣裙", 459),
        ("修身斜纹休闲裤", 279),
        ("羊皮芭蕾平底鞋", 399),
        ("羊毛混纺沙发毯", 359),
    ]
    assert len(products) == 24
    assert [(p["title"], p["price"]) for p in products] == [
        (name, Decimal(price)) for name, price in expected
    ]
    for index, product in enumerate(products):
        attributes = product["attributes"]
        missing = {
            key
            for key in required_attributes_for(product["category"])
            if key not in attributes or not attributes[key]["value"]
        }
        assert missing == ({"产地"} if index == 2 else set())
        assert product["image_url"] == (
            None if index == 5 else f"/demo/products/{index + 1:02d}.webp"
        )
        assert product["stock_on_hand"] == (3 if index == 3 else 100)
        assert product["status"] == ("AUDITING" if index % 8 == 0 else "ONLINE")
    assert products[4]["detail_description"] == "简短说明。"


def test_storefront_catalog_preserves_original_ids_and_listing_dates() -> None:
    from app.analytics.demo_data import build_demo_catalog

    expected = {
        0: ("bb683d33-a395-4677-ae18-b56f3ba0f297", "2026-04-26T02:00:00+00:00"),
        12: ("ca7e9c69-680e-40df-bafb-aeb554821c4c", "2026-03-23T02:00:00+00:00"),
        23: ("14a3e0cc-c851-4a42-a8a0-bb8566bd1186", "2026-03-11T02:00:00+00:00"),
    }
    for _ in range(2):
        products = build_demo_catalog(merchant_id=MERCHANT, seed=DEMO_ANALYTICS_SEED_BASE)
        for index, pair in expected.items():
            assert (str(products[index]["id"]), products[index]["listed_at"].isoformat()) == pair
