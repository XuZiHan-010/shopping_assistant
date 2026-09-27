"""S1–S4 确定性演示场景；仅允许在固定三商家的本地演示库写入。"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import NamedTuple
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.dates import business_today
from app.analytics.demo_data import _event_row
from app.analytics.seed_safety import assert_local_database_url, reject_production
from app.core.config import get_settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.jobs.seed_demo_rolling import _require_demo_merchants
from app.models.analytics import Order, OrderItem, Product
from app.models.drafts import Draft
from app.models.events import FulfillmentEvent, InventoryEvent
from app.models.memory_v2 import CustomerSignal, DailyBrief
from app.models.promotion import Coupon
from app.services.seed_service import default_merchants


class ScenarioRows(NamedTuple):
    coupons: list[dict[str, object]]
    signals: list[dict[str, object]]
    drafts: list[dict[str, object]]
    daily_briefs: list[dict[str, object]]
    orders: list[dict[str, object]]
    order_items: list[dict[str, object]]
    inventory_events: list[dict[str, object]]
    fulfillment_events: list[dict[str, object]]


def _id(merchant_id: UUID, scenario: str, business_day: date) -> UUID:
    return uuid5(NAMESPACE_URL, f"borough-demo:{merchant_id}:{business_day}:{scenario}")


def _moment(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC)


def build_scenario_rows(
    *,
    merchant_id: UUID,
    business_day: date,
    catalog: list[dict[str, object]],
    buyer_key: str | None = None,
) -> ScenarioRows:
    """所有场景时间由营业日锚定，行 ID 与事件去重键可跨运行复现。"""

    by_code = {str(product["product_code"]): product for product in catalog}
    guide = by_code["SKU0001"]
    gap = by_code["SKU0002"]
    low_stock = by_code["SKU0003"]
    if not all(p["status"] == "ONLINE" for p in (guide, gap, low_stock)):
        raise ValueError("S1–S3 商品必须已上架")
    if "产地" in gap["attributes"]:
        raise ValueError("S2 商品必须缺少产地属性")
    if low_stock["stock_on_hand"] - low_stock["stock_reserved"] != 3:
        raise ValueError("S3 商品可售量必须为 3")

    created_at = _moment(business_day, 9)
    order_day = business_day - timedelta(days=4)
    placed_at = _moment(order_day, 10)
    paid_at = _moment(order_day, 12)
    order_id = _id(merchant_id, "s4-order", business_day)
    item_id = _id(merchant_id, "s4-item", business_day)
    unit_price = Decimal(str(guide["price"]))
    order = {
        "id": order_id,
        "merchant_id": merchant_id,
        "business_date": order_day,
        "order_no": f"S4-{business_day:%Y%m%d}-{merchant_id.hex[:8]}",
        "buyer_key": buyer_key or f"borough-demo-buyer-{merchant_id.hex[-4:]}",
        "address_city_name": "上海市",
        "order_status": "COMPLETED",
        "payment_status": "PAID",
        "fulfillment_status": "DELIVERED",
        "after_sale_status": "NONE",
        "close_reason": None,
        "lifecycle_origin": "V2",
        "source_timezone": "Asia/Shanghai",
        "total_amount": unit_price,
        "paid_amount": unit_price,
        "placed_at": placed_at,
        "paid_at": paid_at,
        "created_at": placed_at,
        "updated_at": paid_at + timedelta(days=3),
    }
    item = {
        "id": item_id,
        "merchant_id": merchant_id,
        "business_date": order_day,
        "order_id": order_id,
        "product_id": guide["id"],
        "quantity": 1,
        "unit_price": unit_price,
        "discount_amount": Decimal("0.00"),
        "line_total": unit_price,
        "item_amount": unit_price,
        "created_at": placed_at,
    }
    event_times = (
        ("ORDER_PLACED", placed_at),
        ("PAYMENT_CONFIRMED", paid_at),
        ("SHIPPED", paid_at + timedelta(hours=6)),
        ("IN_TRANSIT", paid_at + timedelta(days=1)),
        ("DELIVERED", paid_at + timedelta(days=3)),
    )
    fulfillment_events = [
        _event_row(
            merchant_id=merchant_id,
            subject_id=order_id,
            event_type=kind,
            occurred_at=moment,
            dedupe_key=f"scenario:s4:{order_id}:{kind}",
            payload={"origin": "V2_DEMO_SEED"},
        )
        for kind, moment in event_times
    ]
    stock_event = _event_row(
        merchant_id=merchant_id,
        subject_id=guide["id"],
        event_type="ORDER_FULFILLED",
        occurred_at=paid_at + timedelta(hours=6),
        dedupe_key=f"scenario:s4:{order_id}:stock-deducted",
        payload={"quantity": -1, "order_id": str(order_id), "origin": "V2_DEMO_SEED"},
    )
    coupon = {
        "id": _id(merchant_id, "s1-coupon", business_day),
        "merchant_id": merchant_id,
        "name": "Borough 演示满减券",
        "kind": "FULL_REDUCTION",
        "threshold_amount": Decimal("50.00"),
        "discount_amount": Decimal("5.00"),
        "discount_rate": None,
        "scope": "ALL",
        "product_ids": [],
        "starts_at": _moment(business_day - timedelta(days=1), 0),
        "ends_at": _moment(business_day + timedelta(days=30), 23),
        "state": "ACTIVE",
        "created_at": created_at,
    }
    signal = {
        "id": _id(merchant_id, "s2-content-gap", business_day),
        "merchant_id": merchant_id,
        "kind": "CONTENT_GAP",
        "product_id": gap["id"],
        "product_name": gap["title"],
        "signal_date": business_day,
        "count": 1,
        "derived_from": [
            {
                "source_type": "PRODUCT",
                "source_id": str(gap["id"]),
                "content_version": gap["content_version"],
            }
        ],
        "is_ignored": False,
        "ignore_reason": None,
        "created_at": created_at,
    }
    draft = {
        "id": _id(merchant_id, "s3-restock", business_day),
        "merchant_id": merchant_id,
        "kind": "RESTOCK",
        "title": "低库存商品补货",
        "target_type": "PRODUCT",
        "target_id": low_stock["id"],
        "target_version": low_stock["stock_on_hand"],
        "draft_version": 1,
        "state": "STAGED",
        "payload": {"quantity": 20, "stock_on_hand_before": low_stock["stock_on_hand"]},
        "guardrail_snapshot": {"stock_available": 3, "low_stock_threshold": 5},
        "created_by": "DEMO_SEED",
        "created_at": created_at,
        "updated_at": created_at,
        "expires_at": created_at + timedelta(days=7),
    }
    brief = {
        "id": _id(merchant_id, "s3-brief", business_day),
        "merchant_id": merchant_id,
        "business_date": business_day,
        "brief_version": 1,
        "payload": {
            "business_timezone": "Asia/Shanghai",
            "data_as_of": created_at.isoformat(),
            "trigger": "SCHEDULED",
            "collapsed_count": 0,
            "items": [
                {
                    "rank": 1,
                    "kind": "INVENTORY_ALERT",
                    "title": "低库存商品待补货",
                    "evidence": f"{low_stock['title']} 可售 3 件",
                    "amount_cents": None,
                    "next_action_prompt": "查看并批准补货草稿",
                },
                {
                    "rank": 2,
                    "kind": "PENDING_DRAFT",
                    "title": "补货草稿待批准",
                    "evidence": "计划补货 20 件",
                    "amount_cents": None,
                    "next_action_prompt": "核对当前库存后批准",
                },
            ],
        },
        "generated_at": created_at,
    }
    return ScenarioRows(
        [coupon],
        [signal],
        [draft],
        [brief],
        [order],
        [item],
        [stock_event],
        fulfillment_events,
    )


async def seed_scenarios(
    session: AsyncSession,
    *,
    business_day: date,
    buyer_keys: dict[str, str] | None = None,
) -> int:
    """在单事务内补齐三家商家的场景，重复运行不叠加订单或扣库存。"""

    await _require_demo_merchants(session)
    written = 0
    for merchant in default_merchants():
        catalog = [
            dict(row)
            for row in (
                await session.execute(
                    select(Product.__table__)
                    .where(Product.merchant_id == merchant.id)
                    .order_by(Product.product_code)
                )
            )
            .mappings()
            .all()
        ]
        if len(catalog) != 24:
            raise RuntimeError("请先运行完整经营种子，商品目录必须恰有 24 条")
        rows = build_scenario_rows(
            merchant_id=merchant.id,
            business_day=business_day,
            catalog=catalog,
            buyer_key=(buyer_keys or {}).get(f"borough-{merchant.merchant_code[-3:]}"),
        )
        for model, records in (
            (Coupon, rows.coupons),
            (CustomerSignal, rows.signals),
            (Draft, rows.drafts),
            (DailyBrief, rows.daily_briefs),
        ):
            statement = (
                insert(model).values(records).on_conflict_do_nothing(index_elements=[model.id])
                .returning(model.id)
            )
            result = await session.execute(statement)
            written += len(result.scalars().all())

        order_result = await session.execute(
            insert(Order)
            .values(rows.orders)
            .on_conflict_do_nothing(index_elements=[Order.id])
            .returning(Order.id)
        )
        if order_result.scalar_one_or_none() is None:
            continue
        await session.execute(insert(OrderItem).values(rows.order_items))
        await session.execute(insert(FulfillmentEvent).values(rows.fulfillment_events))
        await session.execute(insert(InventoryEvent).values(rows.inventory_events))
        product_id = rows.order_items[0]["product_id"]
        stock_result = await session.execute(
            update(Product)
            .where(
                Product.id == product_id,
                Product.merchant_id == merchant.id,
                Product.stock_on_hand - Product.stock_reserved >= 1,
            )
            .values(stock_on_hand=Product.stock_on_hand - 1)
        )
        if stock_result.rowcount != 1:
            raise RuntimeError("S4 商品库存不足，整个场景事务须回滚")
        written += 2 + len(rows.fulfillment_events) + len(rows.inventory_events)
    return written


async def _main_async(business_day: date) -> int:
    settings = get_settings()
    assert_local_database_url(settings.database_url)
    reject_production(settings)
    database = Database(settings)
    try:
        async with database.session() as session:
            written = await seed_scenarios(
                session,
                business_day=business_day,
                buyer_keys=settings.demo_customer_identities,
            )
            await session.commit()
        return written
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="写入可重复的 S1–S4 演示场景")
    parser.add_argument("--business-day", type=date.fromisoformat, default=None)
    parser.add_argument("--seed", action="store_true", help="明确写入本地固定三商家演示库")
    args = parser.parse_args()
    if not args.seed:
        parser.error("写入场景必须显式提供 --seed")
    configure_event_loop_policy()
    settings = get_settings()
    day = args.business_day or business_today(
        datetime.now(UTC), timezone=settings.business_timezone
    )
    written = asyncio.run(_main_async(day))
    print(f"已写入 {written} 条演示场景记录；营业日 {day}")


if __name__ == "__main__":
    main()
