"""顾客下单（交易计划 Task 3，契约 §8.10.3）——真实 PostgreSQL，经真实路由与会话。

并发与行锁在 `tests/integration/v2/test_checkout_concurrency.py`；这里验证 HTTP 契约：
金额只由后端计算、幂等重放原响应、不可用项明确列出、访客不能下单。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import Database
from app.models.analytics import OrderItem
from app.models.promotion import Coupon
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import seed_paid_order, seed_product
from tests.support.trade import (
    OTHER_SHOP,
    SHOP,
    bound_customer,
    count_orders,
    database_of,
    get_order,
    put_cart,
    set_order,
    set_product,
    stock,
)

ORDERS = "/api/v2/shop/orders"


async def _coupon(database: Database, merchant_id: UUID, **overrides: Any) -> str:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "merchant_id": merchant_id,
        "name": "满 100 减 10",
        "kind": "FULL_REDUCTION",
        "threshold_amount": Decimal("100.00"),
        "discount_amount": Decimal("10.00"),
        "discount_rate": None,
        "scope": "SHOP",
        "product_ids": [],
        "starts_at": now - timedelta(days=1),
        "ends_at": now + timedelta(days=1),
        "state": "ACTIVE",
    }
    values.update(overrides)
    async with database.session() as session:
        coupon = Coupon(**values)
        session.add(coupon)
        await session.commit()
        return str(coupon.id)


async def _order(
    client: AsyncClient, headers: dict[str, str], crid: str = "r1", **extra: Any
) -> Any:
    return await client.post(ORDERS, json={"client_request_id": crid, **extra}, headers=headers)


@pytest.mark.asyncio
async def test_order_is_priced_by_the_backend_and_reserves_stock(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid, 3)

    resp = await _order(postgres_client, headers)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["payment_status"] == "PENDING"
    assert body["fulfillment_status"] == "NOT_SHIPPED"
    assert body["after_sale_status"] == "NONE"
    assert body["is_demo"] is True
    assert body["subtotal_cents"] == body["total_cents"] == 30000
    assert body["discount_cents"] == 0 and body["coupon_id"] is None
    assert body["item_count"] == 3
    assert [(i["product_id"], i["quantity"], i["unit_price_cents"]) for i in body["items"]] == [
        (str(pid), 3, 10000)
    ]
    created = datetime.fromisoformat(body["created_at"])
    assert datetime.fromisoformat(body["pay_by"]) - created == timedelta(minutes=30)
    assert body["paid_at"] is None and body["closed_at"] is None and body["close_reason"] is None
    assert (await stock(database, pid)).reserved == 3
    cart = (await postgres_client.get("/api/v2/shop/cart", headers=headers)).json()
    assert cart["items"] == []
    flat = json.dumps(body)
    for leak in ("buyer_key", "merchant_id", "stock_on_hand", "stock_reserved", "buyer-a"):
        assert leak not in flat


@pytest.mark.asyncio
async def test_duplicate_submission_replays_the_original_response(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid, 1)

    first = await _order(postgres_client, headers, "r1")
    second = await _order(postgres_client, headers, "r1")

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert (await stock(database, pid)).reserved == 1
    assert await count_orders(database) == 1


@pytest.mark.asyncio
async def test_same_request_id_with_different_input_is_rejected(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    coupon = await _coupon(database, MERCHANT_ONE_ID, threshold_amount=None)
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid, 1)
    assert (await _order(postgres_client, headers, "r1")).status_code == 201

    reused = await _order(postgres_client, headers, "r1", coupon_id=coupon)

    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_another_customer_may_reuse_the_same_request_id(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    alice = await bound_customer(postgres_client, postgres_app, buyer_key="alice")
    await put_cart(postgres_client, alice, pid, 1)
    bob = await bound_customer(postgres_client, postgres_app, buyer_key="bob")
    await put_cart(postgres_client, bob, pid, 2)

    first = await _order(postgres_client, alice, "same-id")
    second = await _order(postgres_client, bob, "same-id")

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert second.json()["item_count"] == 2


@pytest.mark.asyncio
async def test_client_supplied_amounts_are_rejected(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")

    for extra in ({"total_cents": 1}, {"items": []}, {"buyer_key": "x"}):
        resp = await _order(postgres_client, headers, **extra)
        assert resp.status_code == 422
        assert resp.json()["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
async def test_price_snapshot_is_fixed_at_order_time(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid, 1)
    await set_product(database, pid, price=Decimal("88.80"))  # 加购后改价：以下单时为准

    order = (await _order(postgres_client, headers)).json()
    await set_product(database, pid, price=Decimal("999.00"))  # 下单后改价：不影响快照

    assert order["items"][0]["unit_price_cents"] == 8880
    async with database.session() as session:
        item = (
            await session.execute(select(OrderItem).where(OrderItem.order_id == UUID(order["id"])))
        ).scalar_one()
    assert item.unit_price == Decimal("88.80")


@pytest.mark.asyncio
async def test_amount_off_coupon_is_snapshotted_per_line(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid_a = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    pid_b = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    coupon = await _coupon(database, MERCHANT_ONE_ID)
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid_a, 1)
    await put_cart(postgres_client, headers, pid_b, 2)

    body = (await _order(postgres_client, headers, coupon_id=coupon)).json()

    by_product = {i["product_id"]: i for i in body["items"]}
    assert by_product[str(pid_a)]["discount_cents"] == 333
    assert by_product[str(pid_b)]["discount_cents"] == 667
    assert body["discount_cents"] == 1000
    assert body["total_cents"] == 29000
    assert body["coupon_id"] == coupon


@pytest.mark.asyncio
async def test_percent_off_coupon_uses_the_payment_ratio(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    coupon = await _coupon(
        database,
        MERCHANT_ONE_ID,
        kind="DISCOUNT",
        threshold_amount=None,
        discount_amount=None,
        discount_rate=Decimal("0.20"),
    )
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid, 1)

    body = (await _order(postgres_client, headers, coupon_id=coupon)).json()

    assert body["total_cents"] == 8000


@pytest.mark.asyncio
async def test_unusable_coupons_are_one_indistinguishable_error(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    now = datetime.now(UTC)
    expired = await _coupon(
        database,
        MERCHANT_ONE_ID,
        starts_at=now - timedelta(days=3),
        ends_at=now - timedelta(days=1),
    )
    foreign = await _coupon(database, MERCHANT_TWO_ID)
    too_high = await _coupon(database, MERCHANT_ONE_ID, threshold_amount=Decimal("500.00"))
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid, 1)

    bodies = []
    for index, coupon in enumerate((expired, foreign, too_high, "not-a-uuid")):
        resp = await _order(postgres_client, headers, f"c{index}", coupon_id=coupon)
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "INVALID_REQUEST"
        bodies.append(resp.json()["details"])

    assert all(
        details == [{"field": "coupon_id", "reason": "COUPON_UNAVAILABLE"}] for details in bodies
    )
    assert (await stock(database, pid)).reserved == 0
    assert await count_orders(database) == 0


@pytest.mark.asyncio
async def test_empty_cart_cannot_be_ordered(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")

    resp = await _order(postgres_client, headers)

    assert resp.status_code == 422
    assert resp.json()["details"] == [{"field": "cart", "reason": "EMPTY"}]


@pytest.mark.asyncio
async def test_insufficient_stock_lists_the_line_with_only_a_band(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=4)
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid, 5)

    resp = await _order(postgres_client, headers)

    assert resp.status_code == 409
    assert resp.json()["code"] == "INSUFFICIENT_STOCK"
    assert resp.json()["details"] == [
        {"product_id": str(pid), "reason": "INSUFFICIENT_STOCK", "stock_band": "LOW_STOCK"}
    ]


@pytest.mark.asyncio
async def test_delisted_line_is_product_not_in_scope(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-a")
    await put_cart(postgres_client, headers, pid, 1)
    await set_product(database, pid, status="OFFLINE")

    resp = await _order(postgres_client, headers)

    assert resp.status_code == 403
    assert resp.json()["code"] == "PRODUCT_NOT_IN_SCOPE"
    assert resp.json()["details"] == [
        {"product_id": str(pid), "reason": "DELISTED", "stock_band": "OUT_OF_STOCK"}
    ]


@pytest.mark.asyncio
async def test_guest_cannot_place_orders(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    created = await postgres_client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    headers = {"X-Session-Id": created.json()["session_id"]}

    resp = await _order(postgres_client, headers)

    assert resp.status_code == 403
    assert resp.json()["code"] == "CUSTOMER_BINDING_REQUIRED"


# ---- 支付与取消（Task 4）------------------------------------------------------------


async def _placed(
    client: AsyncClient, app: FastAPI, *, buyer_key: str = "buyer-a", qty: int = 1
) -> tuple[dict[str, str], str, UUID]:
    database = database_of(app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    headers = await bound_customer(client, app, buyer_key=buyer_key)
    await put_cart(client, headers, pid, qty)
    resp = await _order(client, headers, f"place-{buyer_key}")
    assert resp.status_code == 201, resp.text
    return headers, resp.json()["id"], pid


def _public(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key != "request_id"}


@pytest.mark.asyncio
async def test_pay_then_pay_again_is_an_illegal_transition(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, oid, pid = await _placed(postgres_client, postgres_app, qty=2)

    paid = await postgres_client.post(
        f"{ORDERS}/{oid}/pay", json={"client_request_id": "p1"}, headers=headers
    )
    replay = await postgres_client.post(
        f"{ORDERS}/{oid}/pay", json={"client_request_id": "p1"}, headers=headers
    )
    again = await postgres_client.post(
        f"{ORDERS}/{oid}/pay", json={"client_request_id": "p2"}, headers=headers
    )

    assert paid.status_code == replay.status_code == 200
    assert paid.json() == replay.json()
    assert paid.json()["payment_status"] == "PAID"
    assert again.status_code == 409
    assert again.json()["code"] == "ILLEGAL_STATE_TRANSITION"
    assert again.json()["details"] == [{"payment_status": "PAID"}]
    assert (await stock(database_of(postgres_app), pid)).on_hand == 8


@pytest.mark.asyncio
async def test_cancel_closes_the_order_with_the_public_reason(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, oid, pid = await _placed(postgres_client, postgres_app, qty=2)

    resp = await postgres_client.post(
        f"{ORDERS}/{oid}/cancel", json={"client_request_id": "c1"}, headers=headers
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["payment_status"] == "CLOSED"
    assert body["close_reason"] == "USER_CANCELLED"
    assert body["closed_at"] is not None
    assert (await stock(database_of(postgres_app), pid)).reserved == 0


@pytest.mark.asyncio
async def test_expired_order_payment_is_rejected_and_closed(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, oid, pid = await _placed(postgres_client, postgres_app, qty=2)
    await set_order(
        database_of(postgres_app), oid, placed_at=datetime.now(UTC) - timedelta(minutes=33)
    )

    resp = await postgres_client.post(
        f"{ORDERS}/{oid}/pay", json={"client_request_id": "p1"}, headers=headers
    )

    assert resp.status_code == 409
    assert resp.json()["details"] == [{"payment_status": "CLOSED"}]
    order = await get_order(database_of(postgres_app), oid)
    assert order.payment_status == "CLOSED" and order.close_reason == "TIMEOUT"
    assert (await stock(database_of(postgres_app), pid)).reserved == 0


@pytest.mark.asyncio
async def test_other_customers_orders_are_indistinguishable_from_missing(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _, alice_order, pid = await _placed(postgres_client, postgres_app, buyer_key="alice")
    bob = await bound_customer(postgres_client, postgres_app, buyer_key="bob")

    bodies = []
    for target in (alice_order, str(uuid4()), "not-a-uuid"):
        for action in ("pay", "cancel"):
            resp = await postgres_client.post(
                f"{ORDERS}/{target}/{action}", json={"client_request_id": "x1"}, headers=bob
            )
            assert resp.status_code == 403, resp.text
            bodies.append(_public(resp.json()))

    assert all(body == bodies[0] for body in bodies)
    assert bodies[0]["code"] == "RESOURCE_FORBIDDEN" and bodies[0]["details"] == []
    assert (await get_order(database_of(postgres_app), alice_order)).payment_status == "PENDING"
    assert (await stock(database_of(postgres_app), pid)).reserved == 1


# ---- 列表、详情与履约事件（Task 5）--------------------------------------------------


@pytest.mark.asyncio
async def test_detail_and_list_return_the_three_dimensional_projection(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, oid, _ = await _placed(postgres_client, postgres_app, qty=2)
    await postgres_client.post(
        f"{ORDERS}/{oid}/pay", json={"client_request_id": "p1"}, headers=headers
    )

    detail = await postgres_client.get(f"{ORDERS}/{oid}", headers=headers)
    listing = await postgres_client.get(ORDERS, headers=headers)

    assert detail.status_code == listing.status_code == 200
    body = detail.json()
    assert (body["payment_status"], body["fulfillment_status"], body["after_sale_status"]) == (
        "PAID",
        "NOT_SHIPPED",
        "NONE",
    )
    assert "events" not in body  # 详情不内嵌事件数组（§8.10.2 不变量 1）
    page = listing.json()
    assert [o["id"] for o in page["items"]] == [oid]
    assert page["items"][0]["item_count"] == 2
    assert page["has_more"] is False and page["next_cursor"] is None
    assert "items" not in page["items"][0]  # 列表只出摘要


@pytest.mark.asyncio
async def test_detail_keeps_the_price_snapshot_after_a_price_change(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, oid, pid = await _placed(postgres_client, postgres_app)
    await set_product(database_of(postgres_app), pid, price=Decimal("999.00"), title="改名了")

    item = (await postgres_client.get(f"{ORDERS}/{oid}", headers=headers)).json()["items"][0]

    assert item["unit_price_cents"] == 10000
    assert item["name"] == "测试商品"


@pytest.mark.asyncio
async def test_orders_are_listed_newest_first_with_a_bound_cursor(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=50)
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="pager")
    ids = []
    for index in range(3):
        await put_cart(postgres_client, headers, pid, 1)
        ids.append((await _order(postgres_client, headers, f"o{index}")).json()["id"])
        await set_order(
            database, ids[-1], placed_at=datetime.now(UTC) - timedelta(minutes=10 - index)
        )

    first = (await postgres_client.get(ORDERS, params={"limit": 2}, headers=headers)).json()
    second = (
        await postgres_client.get(
            ORDERS, params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers
        )
    ).json()
    other = await bound_customer(postgres_client, postgres_app, buyer_key="someone-else")
    stolen = await postgres_client.get(
        ORDERS, params={"limit": 2, "cursor": first["next_cursor"]}, headers=other
    )

    assert [o["id"] for o in first["items"]] == [ids[2], ids[1]]
    assert first["has_more"] is True
    assert [o["id"] for o in second["items"]] == [ids[0]]
    assert stolen.status_code == 422
    assert stolen.json()["code"] == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_same_buyer_in_another_shop_cannot_see_these_orders(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """跨店双重过滤：同一个 buyer_key 在别家店也只看得到别家店自己的订单。"""

    _, oid, _ = await _placed(postgres_client, postgres_app, buyer_key="shared-buyer")
    other_shop = await bound_customer(
        postgres_client, postgres_app, buyer_key="shared-buyer", shop_slug=OTHER_SHOP
    )

    listing = await postgres_client.get(ORDERS, headers=other_shop)
    detail = await postgres_client.get(f"{ORDERS}/{oid}", headers=other_shop)
    events = await postgres_client.get(f"{ORDERS}/{oid}/events", headers=other_shop)

    assert listing.json()["items"] == []
    assert detail.status_code == events.status_code == 403
    assert detail.json()["code"] == events.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_detail_of_foreign_missing_and_legacy_orders_is_one_403(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    _, alice_order, pid = await _placed(postgres_client, postgres_app, buyer_key="alice")
    legacy = await seed_paid_order(database, MERCHANT_ONE_ID, pid, quantity=1)
    await set_order(database, legacy, buyer_key="bob", lifecycle_origin="LEGACY_V1")
    bob = await bound_customer(postgres_client, postgres_app, buyer_key="bob")

    bodies = []
    for target in (alice_order, str(uuid4()), str(legacy), "not-a-uuid"):
        for suffix in ("", "/events"):
            resp = await postgres_client.get(f"{ORDERS}/{target}{suffix}", headers=bob)
            assert resp.status_code == 403, resp.text
            bodies.append(_public(resp.json()))

    assert all(body == bodies[0] for body in bodies)
    assert bodies[0]["details"] == []


@pytest.mark.asyncio
async def test_events_are_ascending_with_source_timezone(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, oid, _ = await _placed(postgres_client, postgres_app)
    await postgres_client.post(
        f"{ORDERS}/{oid}/pay", json={"client_request_id": "p1"}, headers=headers
    )

    page = (
        await postgres_client.get(f"{ORDERS}/{oid}/events", params={"limit": 1}, headers=headers)
    ).json()
    rest = (
        await postgres_client.get(
            f"{ORDERS}/{oid}/events",
            params={"limit": 1, "cursor": page["next_cursor"]},
            headers=headers,
        )
    ).json()

    assert [e["event_type"] for e in page["items"] + rest["items"]] == [
        "ORDER_PLACED",
        "PAYMENT_CONFIRMED",
    ]
    assert all(e["source_timezone"] == "Asia/Shanghai" for e in page["items"] + rest["items"])
    assert rest["has_more"] is False
    assert set(page["items"][0]) == {"id", "event_type", "occurred_at", "source_timezone"}


@pytest.mark.asyncio
async def test_guest_cannot_read_orders(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    created = await postgres_client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    headers = {"X-Session-Id": created.json()["session_id"]}

    resp = await postgres_client.get(ORDERS, headers=headers)

    assert resp.status_code == 403
    assert resp.json()["code"] == "CUSTOMER_BINDING_REQUIRED"
