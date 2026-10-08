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
from app.models.after_sales import AfterSale, AfterSaleLine
from app.models.analytics import Order, OrderItem, Product, SupportTicket
from app.models.drafts import Draft
from app.models.events import AfterSaleEvent, FulfillmentEvent, InventoryEvent
from app.models.memory_v2 import CustomerSignal, DailyBrief
from app.models.promotion import Coupon
from app.services.seed_service import default_merchants
from app.services.v2.orders import PAYMENT_WINDOW


class ScenarioRows(NamedTuple):
    coupons: list[dict[str, object]]
    signals: list[dict[str, object]]
    drafts: list[dict[str, object]]
    daily_briefs: list[dict[str, object]]
    orders: list[dict[str, object]]
    order_items: list[dict[str, object]]
    inventory_events: list[dict[str, object]]
    fulfillment_events: list[dict[str, object]]
    #: W Task 0 步骤 3：订单页只列 v2 交易订单，S4 单独一单不足以覆盖演示状态，
    #: W 补四单，WS 再补「派送中」一单（已签收沿用既有 S4 订单）。
    #: 订单号、行 ID、事件 dedupe_key 均以 `orders-page-*` 前缀单独命名，
    #: 不复用 `orders`/`order_items` 字段，避免打乱既有场景断言
    #: （S3 可售量、S4 库存扣减）对下标的依赖。
    orders_page_orders: list[dict[str, object]]
    orders_page_items: list[dict[str, object]]
    orders_page_fulfillment_events: list[dict[str, object]]
    after_sales: list[dict[str, object]]
    after_sale_lines: list[dict[str, object]]
    after_sale_tickets: list[dict[str, object]]
    #: `rebuild_projections` 只信任事件账本：只有 `payload["order_id"]` 与
    #: `payload["after_sale_status"]` 都存在时才会把某单的 `after_sale_status`
    #: 判定为非 NONE（详见 `app/jobs/rebuild_projections.py`）。缺这一条，
    #: 「售后中」订单会被判为投影漂移。种子数据显式补齐，不改生产写路径。
    after_sale_events: list[dict[str, object]]


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
        "title_snapshot": guide["title"],
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
        # 载荷形状必须与 Agent 起草的补货草稿一致（`app/services/v2/drafts.py`）：
        # 审批页的改动对照与应用处理器都按 `delta` / `base_on_hand` 读取。
        "payload": {
            "delta": 20,
            "base_on_hand": low_stock["stock_on_hand"],
            "product_title": low_stock["title"],
        },
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
        # 接口把这份 payload 原样按 `DailyBriefResponse` 读回，所以必须是完整的响应结构，
        # 字段与 `services/v2/daily_brief.py::build_full_brief` 的确定性汇总一致；
        # 它不是模型分析（R7）。
        "payload": {
            "analysis_sources": [
                {"source": "DATABASE", "degraded": False, "degraded_reason": None}
            ],
            "thinking_steps": [],
            "quality_status": "NOT_RUN",
            "quality_attempts": 0,
            "quality_notes": [],
            "degraded": False,
            "degraded_reason": None,
            "brief_version": 1,
            "business_date": business_day.isoformat(),
            "business_timezone": "Asia/Shanghai",
            "data_as_of": created_at.isoformat(),
            "generated_at": created_at.isoformat(),
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
    (
        orders_page_orders,
        orders_page_items,
        orders_page_events,
        after_sales,
        after_sale_lines,
        after_sale_events,
    ) = _orders_page_scenarios(
        merchant_id=merchant_id,
        business_day=business_day,
        guide=guide,
        buyer_key=buyer_key,
    )

    return ScenarioRows(
        [coupon],
        [signal],
        [draft],
        [brief],
        [order],
        [item],
        [stock_event],
        fulfillment_events,
        orders_page_orders,
        orders_page_items,
        orders_page_events,
        after_sales,
        after_sale_lines,
        [
            {
                "id": _id(merchant_id, "orders-page-after-sale-ticket", business_day),
                "merchant_id": merchant_id,
                "business_date": business_day,
                "ticket_no": f"SCN-AF-{str(sale['id'])[:12]}",
                "order_id": sale["order_id"],
                "after_sale_id": sale["id"],
                "ticket_status": "OPEN",
                "ticket_reason": "售后申请待商家处理",
                "opened_at": sale["created_at"],
                "created_at": sale["created_at"],
                "updated_at": sale["updated_at"],
            }
            for sale in after_sales
        ],
        after_sale_events,
    )


def _orders_page_scenarios(
    *,
    merchant_id: UUID,
    business_day: date,
    guide: dict[str, object],
    buyer_key: str | None,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    """补足 W 商家端与 WS 顾客端订单页所需的五单。

    契约 §8.12.4：订单页只列本店 v2 交易订单。原 S4 场景只写入一笔「已签收」订单，
    不足以覆盖演示状态；这里用同一 `guide` 商品补建其余五单，订单号、行 ID 均由
    `business_day` 派生，重复运行幂等（与 `seed_scenarios` 的 `on_conflict_do_nothing`
    配合）。库存不做真实扣减——这五单只用于订单页展示与状态筛选联调，不参与
    S1–S4 的库存/指标断言；也正因为没有占用，不能预置会被超时关单释放占用的
    「待支付」单，改为一笔已超时关闭的订单。
    """

    unit_price = Decimal(str(guide["price"]))
    buyer = buyer_key or f"borough-demo-buyer-{merchant_id.hex[-4:]}"
    orders: list[dict[str, object]] = []
    items: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    after_sales: list[dict[str, object]] = []
    after_sale_lines: list[dict[str, object]] = []
    after_sale_events: list[dict[str, object]] = []

    def _order_row(
        *,
        suffix: str,
        order_day: date,
        order_status: str,
        payment_status: str,
        fulfillment_status: str,
        after_sale_status: str,
        placed_at: datetime,
        paid_at: datetime | None,
        close_reason: str | None = None,
        closed_at: datetime | None = None,
    ) -> tuple[UUID, UUID]:
        order_id = _id(merchant_id, f"orders-page-{suffix}", business_day)
        item_id = _id(merchant_id, f"orders-page-{suffix}-item", business_day)
        orders.append(
            {
                "id": order_id,
                "merchant_id": merchant_id,
                "business_date": order_day,
                "order_no": f"OP-{suffix.upper()}-{business_day:%Y%m%d}-{merchant_id.hex[:8]}",
                "buyer_key": buyer,
                "address_city_name": "上海市",
                "order_status": order_status,
                "payment_status": payment_status,
                "fulfillment_status": fulfillment_status,
                "after_sale_status": after_sale_status,
                "close_reason": close_reason,
                "lifecycle_origin": "V2",
                "source_timezone": "Asia/Shanghai",
                "total_amount": unit_price,
                "paid_amount": unit_price if paid_at is not None else Decimal("0.00"),
                "placed_at": placed_at,
                "paid_at": paid_at,
                "closed_at": closed_at,
                "created_at": placed_at,
                "updated_at": closed_at or paid_at or placed_at,
            }
        )
        items.append(
            {
                "id": item_id,
                "merchant_id": merchant_id,
                "business_date": order_day,
                "order_id": order_id,
                "product_id": guide["id"],
                "title_snapshot": guide["title"],
                "quantity": 1,
                "unit_price": unit_price,
                "discount_amount": Decimal("0.00"),
                "line_total": unit_price,
                "item_amount": unit_price,
                "created_at": placed_at,
            }
        )
        return order_id, item_id

    # 超时关闭：不预置「待支付」。种子按营业日锚定、行 ID 可复现，而待支付只在下单后
    # 30 分钟内合法（PRD §7.1）；预置的待支付单写入即已过期，且没有库存占用——支付自检或
    # `close_expired_orders` 关单时会把 `stock_reserved` 减成负数（违反
    # `ck_products_stock_reserved_nonneg`）或吃掉别人的占用。这里直接写成它最终会到达的
    # 合法终态；演示「待支付」请现场下单。占用与释放都未发生，所以不写库存事件。
    closed_day = business_day - timedelta(days=1)
    closed_placed = _moment(closed_day, 15)
    closed_at = closed_placed + PAYMENT_WINDOW
    closed_order_id, _ = _order_row(
        suffix="payment-timeout",
        order_day=closed_day,
        order_status="CLOSED",
        payment_status="CLOSED",
        fulfillment_status="NOT_SHIPPED",
        after_sale_status="NONE",
        placed_at=closed_placed,
        paid_at=None,
        close_reason="TIMEOUT",
        closed_at=closed_at,
    )
    for event_type, occurred_at, payload in (
        ("ORDER_PLACED", closed_placed, {"origin": "V2_DEMO_SEED"}),
        ("ORDER_CLOSED", closed_at, {"origin": "V2_DEMO_SEED", "close_reason": "TIMEOUT"}),
    ):
        events.append(
            _event_row(
                merchant_id=merchant_id,
                subject_id=closed_order_id,
                event_type=event_type,
                occurred_at=occurred_at,
                dedupe_key=(
                    f"scenario:orders-page:payment-timeout:{closed_order_id}:{event_type}"
                ),
                payload=payload,
            )
        )

    # 待发货：已支付，尚未发货。
    awaiting_day = business_day - timedelta(days=2)
    awaiting_placed = _moment(awaiting_day, 10)
    awaiting_paid = _moment(awaiting_day, 11)
    awaiting_order_id, _ = _order_row(
        suffix="awaiting-shipment",
        order_day=awaiting_day,
        order_status="PAID",
        payment_status="PAID",
        fulfillment_status="NOT_SHIPPED",
        after_sale_status="NONE",
        placed_at=awaiting_placed,
        paid_at=awaiting_paid,
    )
    for kind, moment in (("ORDER_PLACED", awaiting_placed), ("PAYMENT_CONFIRMED", awaiting_paid)):
        events.append(
            _event_row(
                merchant_id=merchant_id,
                subject_id=awaiting_order_id,
                event_type=kind,
                occurred_at=moment,
                dedupe_key=f"scenario:orders-page:awaiting-shipment:{awaiting_order_id}:{kind}",
                payload={"origin": "V2_DEMO_SEED"},
            )
        )

    # 运输中：已发货，在途。
    transit_day = business_day - timedelta(days=3)
    transit_placed = _moment(transit_day, 9)
    transit_paid = _moment(transit_day, 10)
    transit_order_id, _ = _order_row(
        suffix="in-transit",
        order_day=transit_day,
        order_status="SHIPPED",
        payment_status="PAID",
        fulfillment_status="IN_TRANSIT",
        after_sale_status="NONE",
        placed_at=transit_placed,
        paid_at=transit_paid,
    )
    for kind, moment in (
        ("ORDER_PLACED", transit_placed),
        ("PAYMENT_CONFIRMED", transit_paid),
        ("SHIPPED", transit_paid + timedelta(hours=6)),
        ("IN_TRANSIT", transit_paid + timedelta(days=1)),
    ):
        events.append(
            _event_row(
                merchant_id=merchant_id,
                subject_id=transit_order_id,
                event_type=kind,
                occurred_at=moment,
                dedupe_key=f"scenario:orders-page:in-transit:{transit_order_id}:{kind}",
                payload={"origin": "V2_DEMO_SEED"},
            )
        )

    # 派送中：供 WS 顾客端首页与订单视图展示当天正在派送的订单。
    delivery_day = business_day - timedelta(days=2)
    delivery_placed = _moment(delivery_day, 8)
    delivery_paid = _moment(delivery_day, 9)
    delivery_order_id, _ = _order_row(
        suffix="out-for-delivery",
        order_day=delivery_day,
        order_status="SHIPPED",
        payment_status="PAID",
        fulfillment_status="OUT_FOR_DELIVERY",
        after_sale_status="NONE",
        placed_at=delivery_placed,
        paid_at=delivery_paid,
    )
    for kind, moment in (
        ("ORDER_PLACED", delivery_placed),
        ("PAYMENT_CONFIRMED", delivery_paid),
        ("SHIPPED", delivery_paid + timedelta(hours=6)),
        ("IN_TRANSIT", delivery_paid + timedelta(days=1)),
        ("OUT_FOR_DELIVERY", delivery_paid + timedelta(days=2)),
    ):
        events.append(
            _event_row(
                merchant_id=merchant_id,
                subject_id=delivery_order_id,
                event_type=kind,
                occurred_at=moment,
                dedupe_key=f"scenario:orders-page:out-for-delivery:{delivery_order_id}:{kind}",
                payload={"origin": "V2_DEMO_SEED"},
            )
        )

    # 售后中：已签收，但存在进行中的售后单（after_sale_status=ACTIVE），
    # 配一条真实 `after_sales` 记录，与生产写路径（`after_sale_machine.py`）
    # 「ACTIVE 必有售后记录」的隐含约定保持一致。
    after_sale_day = business_day - timedelta(days=6)
    after_sale_placed = _moment(after_sale_day, 9)
    after_sale_paid = _moment(after_sale_day, 10)
    after_sale_order_id, after_sale_item_id = _order_row(
        suffix="after-sale",
        order_day=after_sale_day,
        order_status="COMPLETED",
        payment_status="PAID",
        fulfillment_status="DELIVERED",
        after_sale_status="ACTIVE",
        placed_at=after_sale_placed,
        paid_at=after_sale_paid,
    )
    for kind, moment in (
        ("ORDER_PLACED", after_sale_placed),
        ("PAYMENT_CONFIRMED", after_sale_paid),
        ("SHIPPED", after_sale_paid + timedelta(hours=6)),
        ("IN_TRANSIT", after_sale_paid + timedelta(days=1)),
        ("DELIVERED", after_sale_paid + timedelta(days=3)),
    ):
        events.append(
            _event_row(
                merchant_id=merchant_id,
                subject_id=after_sale_order_id,
                event_type=kind,
                occurred_at=moment,
                dedupe_key=f"scenario:orders-page:after-sale:{after_sale_order_id}:{kind}",
                payload={"origin": "V2_DEMO_SEED"},
            )
        )
    after_sale_id = _id(merchant_id, "orders-page-after-sale-record", business_day)
    after_sales.append(
        {
            "id": after_sale_id,
            "merchant_id": merchant_id,
            "buyer_key": buyer,
            "order_id": after_sale_order_id,
            "after_sale_type": "RETURN_REFUND",
            "state": "PENDING_MERCHANT",
            "reason": "商品与描述不符，申请退货退款",
            "refund_amount": unit_price,
            "state_version": 1,
            "conversation_summary_status": "NOT_SHARED",
            "conversation_summary_text": None,
            "conversation_summary_reason": None,
            "created_at": after_sale_paid + timedelta(days=4),
            "updated_at": after_sale_paid + timedelta(days=4),
        }
    )
    after_sale_lines.append(
        {
            "id": _id(merchant_id, "orders-page-after-sale-line", business_day),
            "after_sale_id": after_sale_id,
            "order_item_id": after_sale_item_id,
            "quantity": 1,
            "refund_amount": unit_price,
        }
    )
    after_sale_events.append(
        _event_row(
            merchant_id=merchant_id,
            subject_id=after_sale_id,
            event_type="PENDING_MERCHANT",
            occurred_at=after_sale_paid + timedelta(days=4),
            dedupe_key=f"scenario:orders-page:after-sale:{after_sale_id}:1",
            payload={
                "from_state": None,
                "to_state": "PENDING_MERCHANT",
                "actor": "CUSTOMER",
                # 生产写路径（`after_sales.py`/`after_sale_machine.py`）尚未在事件
                # payload 里带 order_id/after_sale_status，`rebuild_projections`
                # 因此永远判定 after_sale_status=NONE。种子数据显式补上这两个键，
                # 让投影检查能识别「售后中」这单，不代表生产事件已改形状。
                "order_id": str(after_sale_order_id),
                "after_sale_status": "ACTIVE",
            },
        )
    )

    return orders, items, events, after_sales, after_sale_lines, after_sale_events


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
        if order_result.scalar_one_or_none() is not None:
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

        # 订单页五单与 S4 各自独立判断冲突，
        # 互不影响：即便 S4 订单已存在（上面 if 分支未进入），这五单
        # 仍可能是首次写入（例如从旧版种子库升级）。
        orders_page_result = await session.execute(
            insert(Order)
            .values(rows.orders_page_orders)
            .on_conflict_do_nothing(index_elements=[Order.id])
            .returning(Order.id)
        )
        inserted_order_ids = set(orders_page_result.scalars().all())
        if inserted_order_ids:
            written += len(inserted_order_ids)
            kept_items = [
                row for row in rows.orders_page_items if row["order_id"] in inserted_order_ids
            ]
            kept_events = [
                row
                for row in rows.orders_page_fulfillment_events
                if row["subject_id"] in inserted_order_ids
            ]
            if kept_items:
                await session.execute(insert(OrderItem).values(kept_items))
                written += len(kept_items)
            if kept_events:
                await session.execute(insert(FulfillmentEvent).values(kept_events))
                written += len(kept_events)
            kept_after_sales = [
                row for row in rows.after_sales if row["order_id"] in inserted_order_ids
            ]
            if kept_after_sales:
                after_sale_result = await session.execute(
                    insert(AfterSale)
                    .values(kept_after_sales)
                    .on_conflict_do_nothing(index_elements=[AfterSale.id])
                    .returning(AfterSale.id)
                )
                inserted_after_sale_ids = set(after_sale_result.scalars().all())
                written += len(inserted_after_sale_ids)
                kept_lines = [
                    row
                    for row in rows.after_sale_lines
                    if row["after_sale_id"] in inserted_after_sale_ids
                ]
                if kept_lines:
                    await session.execute(insert(AfterSaleLine).values(kept_lines))
                    written += len(kept_lines)
                kept_tickets = [
                    row
                    for row in rows.after_sale_tickets
                    if row["after_sale_id"] in inserted_after_sale_ids
                ]
                if kept_tickets:
                    await session.execute(insert(SupportTicket).values(kept_tickets))
                    written += len(kept_tickets)
                kept_after_sale_events = [
                    row
                    for row in rows.after_sale_events
                    if row["subject_id"] in inserted_after_sale_ids
                ]
                if kept_after_sale_events:
                    await session.execute(insert(AfterSaleEvent).values(kept_after_sale_events))
                    written += len(kept_after_sale_events)
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
