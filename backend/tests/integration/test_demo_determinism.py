"""演示数据的跨运行稳定性与 v2 事实账本约束。"""

from __future__ import annotations

import importlib.util
import json
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.demo_data import (
    DEMO_ANALYTICS_SEED_BASE,
    build_demo_catalog,
    build_demo_dataset,
)
from app.jobs.rebuild_projections import _LEGACY_STAGE
from app.models.base import Base
from app.schemas.v2.trade import FulfillmentEventType

_scenario_path = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo_scenarios.py"
_scenario_spec = importlib.util.spec_from_file_location(
    "borough_scenario_seed_for_test", _scenario_path
)
assert _scenario_spec is not None and _scenario_spec.loader is not None
_scenario_module = importlib.util.module_from_spec(_scenario_spec)
_scenario_spec.loader.exec_module(_scenario_module)
_analytics_path = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo_analytics.py"
_analytics_spec = importlib.util.spec_from_file_location(
    "borough_analytics_seed_for_test", _analytics_path
)
assert _analytics_spec is not None and _analytics_spec.loader is not None
_analytics_module = importlib.util.module_from_spec(_analytics_spec)
_analytics_spec.loader.exec_module(_analytics_module)

MERCHANT_ONE = UUID("00000000-0000-0000-0000-000000000001")
MERCHANT_TWO = UUID("00000000-0000-0000-0000-000000000002")
END_DATE = date(2026, 9, 22)


def _dataset(merchant_id: UUID = MERCHANT_ONE, seed: int = DEMO_ANALYTICS_SEED_BASE):
    return build_demo_dataset(merchant_id=merchant_id, end_date=END_DATE, days=30, seed=seed)


def test_same_seed_produces_identical_dataset() -> None:
    assert _dataset() == _dataset()


def test_different_merchants_get_different_data() -> None:
    assert _dataset() != _dataset(MERCHANT_TWO, DEMO_ANALYTICS_SEED_BASE + 1)


def test_catalog_contains_all_four_completeness_samples() -> None:
    catalog = build_demo_catalog(merchant_id=MERCHANT_ONE, seed=DEMO_ANALYTICS_SEED_BASE)
    assert any(
        "产地" in product["attributes"]
        and product["image_url"]
        and len(product["detail_description"] or "") > 100
        for product in catalog
    )
    assert any("产地" not in product["attributes"] for product in catalog)
    assert any(len(product["detail_description"] or "") < 30 for product in catalog)
    assert any(product["image_url"] is None for product in catalog)


def test_catalog_stock_matches_initial_stock_ledger() -> None:
    dataset = _dataset()
    initial = {
        event["subject_id"]: event
        for event in dataset.inventory_events
        if event["event_type"] == "INITIAL_STOCK"
    }
    assert len(initial) == len(dataset.products)
    for product in dataset.products:
        assert product["stock_on_hand"] >= product["stock_reserved"]
        assert initial[product["id"]]["payload"]["quantity"] == product["stock_on_hand"]


def test_legacy_orders_have_matching_projection_snapshots_and_events() -> None:
    dataset = _dataset()
    events_by_order: dict[UUID, dict[str, dict[str, object]]] = {}
    for event in dataset.fulfillment_events:
        events_by_order.setdefault(event["subject_id"], {})[event["event_type"]] = event

    items_by_order: dict[UUID, list[dict[str, object]]] = {}
    for item in dataset.order_items:
        items_by_order.setdefault(item["order_id"], []).append(item)
        assert item["line_total"] == item["item_amount"]
        assert item["unit_price"] * item["quantity"] - item["discount_amount"] == item["line_total"]

    for order in dataset.orders:
        assert order["lifecycle_origin"] == "LEGACY_V1"
        assert order["after_sale_status"] == "NONE"
        assert (
            sum(item["line_total"] for item in items_by_order[order["id"]]) == order["total_amount"]
        )
        events = events_by_order[order["id"]]
        assert events["ORDER_PLACED"]["occurred_at"] == order["placed_at"]
        assert events["ORDER_PLACED"]["payload"]["origin"] == "LEGACY_V1_BACKFILL"
        if order["order_status"] in {"PAID", "SHIPPED", "COMPLETED"}:
            assert events["PAYMENT_CONFIRMED"]["occurred_at"] == order["paid_at"]
            assert events["PAYMENT_CONFIRMED"]["payload"]["origin"] == "LEGACY_V1_BACKFILL"
        if order["order_status"] in {"SHIPPED", "COMPLETED"}:
            paid_at = events["PAYMENT_CONFIRMED"]["occurred_at"]
            assert events["SHIPPED"]["occurred_at"] - paid_at == timedelta(hours=6)
            assert events["SHIPPED"]["payload"]["time_inferred"] is True
        if order["order_status"] == "COMPLETED":
            paid_at = events["PAYMENT_CONFIRMED"]["occurred_at"]
            assert events["DELIVERED"]["occurred_at"] - paid_at == timedelta(days=3)
        if order["order_status"] in {"CANCELLED", "CLOSED"}:
            assert events["ORDER_CLOSED"]["payload"]["close_reason"] == order["close_reason"]


def test_fulfillment_event_types_match_the_v2_contract() -> None:
    """账本只允许追加，事件名写错后无法改正，必须与契约枚举逐字一致。"""
    contract = {member.value for member in FulfillmentEventType}
    assert {e["event_type"] for e in _dataset().fulfillment_events} <= contract
    assert set(_LEGACY_STAGE) == contract


def test_paid_order_placement_precedes_payment() -> None:
    for order in _dataset().orders:
        if order["payment_status"] == "PAID":
            assert order["placed_at"] <= order["paid_at"]


def test_catalog_price_and_inventory_have_valid_units() -> None:
    for product in _dataset().products:
        assert isinstance(product["price"], Decimal)
        assert product["price"] > 0
        assert product["stock_on_hand"] >= 0


def test_all_generated_business_rows_have_reproducible_audit_times() -> None:
    dataset = _dataset()
    for rows in (
        dataset.products,
        dataset.orders,
        dataset.order_items,
        dataset.refunds,
        dataset.returns,
        dataset.tickets,
        dataset.inventory_events,
        dataset.fulfillment_events,
    ):
        assert all(row["created_at"].tzinfo is not None for row in rows)
    assert all(product["updated_at"] == product["created_at"] for product in dataset.products)
    assert all(order["updated_at"] == order["created_at"] for order in dataset.orders)


def test_scenarios_are_stable_and_cover_s1_to_s4() -> None:
    catalog = build_demo_catalog(merchant_id=MERCHANT_ONE, seed=DEMO_ANALYTICS_SEED_BASE)
    first = _scenario_module.build_scenario_rows(
        merchant_id=MERCHANT_ONE, business_day=END_DATE, catalog=catalog
    )
    second = _scenario_module.build_scenario_rows(
        merchant_id=MERCHANT_ONE, business_day=END_DATE, catalog=catalog
    )
    assert first == second

    available = {p["id"]: p for p in catalog if p["status"] == "ONLINE"}
    coupon = first.coupons[0]
    assert coupon["state"] == "ACTIVE"
    assert coupon["starts_at"].date() <= END_DATE <= coupon["ends_at"].date()
    assert any(p["stock_on_hand"] - p["stock_reserved"] > 0 for p in available.values())

    gap = first.signals[0]
    assert gap["kind"] == "CONTENT_GAP"
    assert "产地" not in available[gap["product_id"]]["attributes"]
    assert gap["derived_from"] == [
        {
            "source_type": "PRODUCT",
            "source_id": str(gap["product_id"]),
            "content_version": 1,
        }
    ]

    restock = first.drafts[0]
    low_stock = available[restock["target_id"]]
    assert restock["kind"] == "RESTOCK"
    assert restock["state"] == "STAGED"
    assert low_stock["stock_on_hand"] - low_stock["stock_reserved"] == 3
    assert restock["target_version"] == 3
    history = _dataset()
    sold_last_30d = sum(
        item["quantity"] for item in history.order_items if item["product_id"] == low_stock["id"]
    )
    assert sold_last_30d >= 30

    order = first.orders[0]
    item = first.order_items[0]
    events = {e["event_type"]: e for e in first.fulfillment_events}
    assert order["lifecycle_origin"] == "V2"
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["business_date"] >= END_DATE - timedelta(days=7)
    assert item["line_total"] == item["unit_price"] * item["quantity"] - item["discount_amount"]
    assert order["total_amount"] == item["line_total"]
    paid_at = events["PAYMENT_CONFIRMED"]["occurred_at"]
    assert events["SHIPPED"]["occurred_at"] - paid_at == timedelta(hours=6)
    assert events["DELIVERED"]["occurred_at"] - paid_at == timedelta(days=3)
    assert all("time_inferred" not in e["payload"] for e in first.fulfillment_events)
    assert first.inventory_events[0]["subject_id"] == item["product_id"]
    assert first.inventory_events[0]["payload"]["quantity"] == -item["quantity"]


def test_orders_page_scenario_covers_five_statuses() -> None:
    """W 与 WS 的订单演示覆盖超时关闭、待发货、运输、派送、签收及售后。

    契约 §8.12.4「订单只读、按商家隔离」要求列表只返回本店具备 v2 交易投影的订单；
    原 S1–S4 场景只有 S4 一笔「已签收」订单，本测试钉住补齐后的六单覆盖，
    防止未来改动误删其中任一状态。
    """

    catalog = build_demo_catalog(merchant_id=MERCHANT_ONE, seed=DEMO_ANALYTICS_SEED_BASE)
    first = _scenario_module.build_scenario_rows(
        merchant_id=MERCHANT_ONE, business_day=END_DATE, catalog=catalog
    )
    second = _scenario_module.build_scenario_rows(
        merchant_id=MERCHANT_ONE, business_day=END_DATE, catalog=catalog
    )
    assert first == second

    all_orders = [*first.orders, *first.orders_page_orders]
    assert len(all_orders) == 6
    assert all(order["lifecycle_origin"] == "V2" for order in all_orders)
    assert len({order["id"] for order in all_orders}) == 6  # 无重复 id

    statuses = {
        (order["order_status"], order["payment_status"], order["fulfillment_status"])
        for order in all_orders
    }
    assert statuses == {
        ("CLOSED", "CLOSED", "NOT_SHIPPED"),  # 超时关闭（不预置待支付，见下方断言）
        ("PAID", "PAID", "NOT_SHIPPED"),  # 待发货
        ("SHIPPED", "PAID", "IN_TRANSIT"),  # 运输中
        ("SHIPPED", "PAID", "OUT_FOR_DELIVERY"),  # 派送中
        ("COMPLETED", "PAID", "DELIVERED"),  # 已签收（S4 原单）与售后中共用该组合
    }
    # 种子没有库存占用，且按营业日锚定：预置的待支付单写入即过期，超时关单会把
    # `stock_reserved` 减成负数。只允许已关闭终态，且事件账本与投影一致。
    assert all(order["payment_status"] != "PENDING" for order in all_orders)
    (closed,) = [order for order in all_orders if order["payment_status"] == "CLOSED"]
    assert closed["close_reason"] == "TIMEOUT"
    assert closed["closed_at"] - closed["placed_at"] == timedelta(minutes=30)
    closed_events = [
        event
        for event in first.orders_page_fulfillment_events
        if event["subject_id"] == closed["id"]
    ]
    assert [event["event_type"] for event in closed_events] == ["ORDER_PLACED", "ORDER_CLOSED"]
    assert closed_events[1]["occurred_at"] == closed["closed_at"]
    assert closed_events[1]["payload"]["close_reason"] == "TIMEOUT"

    after_sale_statuses = {order["after_sale_status"] for order in all_orders}
    assert after_sale_statuses == {"NONE", "ACTIVE"}
    active_orders = [o for o in all_orders if o["after_sale_status"] == "ACTIVE"]
    assert len(active_orders) == 1

    # 售后中订单必须有匹配的 after_sales 记录，且 order_id 对应关系正确
    # （与生产写路径 `after_sale_machine.py` 的隐含约定一致，不是纯展示字段）。
    assert len(first.after_sales) == 1
    assert first.after_sales[0]["order_id"] == active_orders[0]["id"]
    assert len(first.after_sale_lines) == 1
    assert first.after_sale_lines[0]["after_sale_id"] == first.after_sales[0]["id"]

    # 订单行、履约事件与订单一一对应，不遗漏。
    order_ids = {order["id"] for order in first.orders_page_orders}
    assert {item["order_id"] for item in first.orders_page_items} == order_ids
    assert {event["subject_id"] for event in first.orders_page_fulfillment_events} == order_ids

    # `rebuild_projections` 只认事件账本：payload 必须同时带 order_id 与
    # after_sale_status，否则「售后中」订单会被判定为投影漂移（详见
    # `app/jobs/rebuild_projections.py` 的 `after_by_order` 匹配逻辑）。
    assert len(first.after_sale_events) == 1
    after_sale_event = first.after_sale_events[0]
    assert after_sale_event["subject_id"] == first.after_sales[0]["id"]
    assert after_sale_event["payload"]["order_id"] == str(active_orders[0]["id"])
    assert after_sale_event["payload"]["after_sale_status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_three_merchant_seed_is_repeatable_in_postgres(db_session: AsyncSession) -> None:
    from app.jobs.rebuild_projections import rebuild_projections
    from app.models.analytics import Order, Product
    from app.models.events import FulfillmentEvent, InventoryEvent
    from app.services.seed_service import default_merchants, seed_demo_merchants

    async def snapshot_digest() -> str:
        # 逐行规范化，覆盖经营事实、事件、库存与 S1–S4 场景。
        tables = (
            "products",
            "orders",
            "order_items",
            "refunds",
            "returns",
            "support_tickets",
            "inventory_events",
            "fulfillment_events",
            "after_sale_events",
            "coupons",
            "customer_signals",
            "drafts",
            "daily_briefs",
        )
        snapshot = {}
        for name in tables:
            table = Base.metadata.tables[name]
            rows = (await db_session.execute(select(table).order_by(table.c.id))).mappings().all()
            snapshot[name] = [dict(row) for row in rows]
        encoded = json.dumps(snapshot, sort_keys=True, default=str, ensure_ascii=False).encode()
        return sha256(encoded).hexdigest()

    await seed_demo_merchants(db_session, default_merchants())
    first_written = await _analytics_module.seed_analytics(db_session, days=7, end_date=END_DATE)
    first_scenarios = await _scenario_module.seed_scenarios(db_session, business_day=END_DATE)
    counts = tuple(
        [
            await db_session.scalar(select(func.count()).select_from(model))
            for model in (Product, Order, InventoryEvent, FulfillmentEvent)
        ]
    )
    product_stock = list(
        await db_session.scalars(select(Product.stock_on_hand).order_by(Product.id))
    )
    report = await rebuild_projections(db_session, dry_run=True)
    first_digest = await snapshot_digest()

    second_scenarios = await _scenario_module.seed_scenarios(db_session, business_day=END_DATE)
    assert first_written > 0
    assert first_scenarios > 0
    assert second_scenarios == 0
    assert counts == tuple(
        [
            await db_session.scalar(select(func.count()).select_from(model))
            for model in (Product, Order, InventoryEvent, FulfillmentEvent)
        ]
    )
    assert product_stock == list(
        await db_session.scalars(select(Product.stock_on_hand).order_by(Product.id))
    )
    assert report.mismatches == 0

    second_written = await _analytics_module.seed_analytics(db_session, days=7, end_date=END_DATE)
    rebuilt_scenarios = await _scenario_module.seed_scenarios(db_session, business_day=END_DATE)
    assert second_written == first_written
    assert rebuilt_scenarios == first_scenarios
    assert await snapshot_digest() == first_digest


@pytest.mark.asyncio
async def test_rolling_prunes_legacy_orders_but_keeps_v2_order_and_event_audit(
    db_session: AsyncSession,
) -> None:
    from app.core.seed_config import SeedSettings
    from app.jobs.seed_demo_rolling import roll_forward
    from app.models.analytics import Order
    from app.models.events import FulfillmentEvent
    from app.services.seed_service import default_merchants, seed_demo_merchants

    await seed_demo_merchants(db_session, default_merchants())
    await _analytics_module.seed_analytics(db_session, days=5, end_date=date(2026, 8, 19))
    await _scenario_module.seed_scenarios(db_session, business_day=date(2026, 8, 19))
    before_events = await db_session.scalar(select(func.count()).select_from(FulfillmentEvent))
    settings = SeedSettings(
        database_url="postgresql+psycopg://borough:borough_local@127.0.0.1:55432/borough_c_seed_test",
        allow_demo_data_refresh=True,
    )
    await roll_forward(db_session, settings=settings, business_day=date(2026, 8, 25), window_days=5)

    # 每个商家的 S1–S4 场景写 1 单（已签收）+ 订单页补齐的 5 单。
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Order).where(Order.lifecycle_origin == "V2")
        )
        == 6 * len(default_merchants())
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.lifecycle_origin == "LEGACY_V1", Order.business_date < date(2026, 8, 21))
        )
        == 0
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(FulfillmentEvent)) > before_events
    )


@pytest.mark.asyncio
async def test_full_rebuild_rejects_extra_merchant_before_writing(db_session: AsyncSession) -> None:
    from app.models.analytics import Product
    from app.models.merchant import Merchant
    from app.services.seed_service import default_merchants, seed_demo_merchants

    await seed_demo_merchants(db_session, default_merchants())
    db_session.add(
        Merchant(
            id=UUID("00000000-0000-0000-0000-0000000000ff"),
            merchant_code="outside-demo-set",
            display_name="非固定演示商家",
        )
    )
    await db_session.flush()
    with pytest.raises(RuntimeError, match="商家集合不匹配"):
        await _analytics_module.seed_analytics(db_session, days=1, end_date=END_DATE)
    assert await db_session.scalar(select(func.count()).select_from(Product)) == 0
