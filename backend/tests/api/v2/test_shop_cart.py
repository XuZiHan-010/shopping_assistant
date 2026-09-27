"""顾客购物车（PRD C3，契约 §8.10）与绑定时的访客购物车合并（D7⑥、E9）。

真实 PostgreSQL：「不占库存」「合并在绑定事务内」「重复绑定不重复合并」只在真库上才有意义。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.api.session_deps import get_cart_merge_port
from app.db.session import Database
from app.models.analytics import Product
from app.models.cart import CartLine
from app.models.operations import AuditLog
from app.services.session_service import EmptyCartMerge
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_product

SHOP = "borough-api-100"
BUYER = "demo-buyer-cart"
QUANTITY_KEYS = ("stock_on_hand", "stock_reserved", "stock_available", "threshold")


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


def _enable_demo_customer(app: FastAPI, *, buyer_key: str = BUYER) -> None:
    app.state.settings.demo_deployment_mode = True
    app.state.settings.demo_customer_identities = {SHOP: buyer_key}


async def _guest(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    assert resp.status_code == 201, resp.text
    return {"X-Session-Id": resp.json()["session_id"]}


async def _bind(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = await client.post("/api/v2/shop/sessions/demo-customer", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def _put(
    client: AsyncClient, headers: dict[str, str], product_id: UUID | str, quantity: int
) -> Any:
    return await client.put(
        f"/api/v2/shop/cart/items/{product_id}", json={"quantity": quantity}, headers=headers
    )


async def _cart(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    resp = await client.get("/api/v2/shop/cart", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _quantities(cart: dict[str, Any]) -> dict[str, int]:
    return {item["product_id"]: item["quantity"] for item in cart["items"]}


async def _stock(database: Database, product_id: UUID) -> tuple[int, int]:
    async with database.session() as session:
        row = (
            await session.execute(
                select(Product.stock_on_hand, Product.stock_reserved).where(
                    Product.id == product_id
                )
            )
        ).one()
    return row.stock_on_hand, row.stock_reserved


async def _set_product(database: Database, product_id: UUID, **values: Any) -> None:
    async with database.session() as session:
        await session.execute(update(Product).where(Product.id == product_id).values(**values))
        await session.commit()


# ---- 基础读写 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cart_does_not_reserve_stock(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """D13：购物车不占库存。"""

    database = _database(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=10)
    headers = await _guest(postgres_client)
    before = await _stock(database, pid)

    resp = await _put(postgres_client, headers, pid, 3)

    assert resp.status_code == 200, resp.text
    assert await _stock(database, pid) == before


@pytest.mark.asyncio
async def test_put_sets_absolute_quantity_and_is_idempotent(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    pid = await seed_product(_database(postgres_app), MERCHANT_ONE_ID)
    headers = await _guest(postgres_client)

    for _ in range(3):
        resp = await _put(postgres_client, headers, pid, 2)
        assert resp.status_code == 200

    cart = await _cart(postgres_client, headers)
    assert _quantities(cart) == {str(pid): 2}
    assert resp.json() == cart


@pytest.mark.asyncio
async def test_cart_prices_come_from_the_product_and_hide_stock_numbers(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    pid_a = await seed_product(database, MERCHANT_ONE_ID, title="甲", on_hand=40)
    pid_b = await seed_product(database, MERCHANT_ONE_ID, title="乙", on_hand=3)
    headers = await _guest(postgres_client)
    await _put(postgres_client, headers, pid_a, 2)
    await _put(postgres_client, headers, pid_b, 1)

    cart = await _cart(postgres_client, headers)

    by_id = {item["product_id"]: item for item in cart["items"]}
    assert by_id[str(pid_a)]["unit_price_cents"] == 10000
    assert by_id[str(pid_a)]["line_total_cents"] == 20000
    assert by_id[str(pid_a)]["stock_band"] == "IN_STOCK"
    assert by_id[str(pid_b)]["stock_band"] == "LOW_STOCK"
    assert cart["subtotal_cents"] == 30000
    flat = json.dumps(cart)
    for leak in (*QUANTITY_KEYS, str(MERCHANT_ONE_ID), "buyer_key"):
        assert leak not in flat


@pytest.mark.asyncio
async def test_zero_quantity_and_delete_remove_the_line(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    pid_a = await seed_product(database, MERCHANT_ONE_ID)
    pid_b = await seed_product(database, MERCHANT_ONE_ID)
    headers = await _guest(postgres_client)
    await _put(postgres_client, headers, pid_a, 1)
    await _put(postgres_client, headers, pid_b, 1)

    zero = await _put(postgres_client, headers, pid_a, 0)
    deleted = await postgres_client.delete(f"/api/v2/shop/cart/items/{pid_b}", headers=headers)

    assert zero.status_code == deleted.status_code == 200
    assert deleted.json() == {"items": [], "subtotal_cents": 0}


@pytest.mark.asyncio
async def test_delete_is_idempotent_and_does_not_probe_existence(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await _guest(postgres_client)

    for target in (uuid4(), "not-a-uuid"):
        resp = await postgres_client.delete(f"/api/v2/shop/cart/items/{target}", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "subtotal_cents": 0}


# ---- 拒绝路径 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_foreign_or_off_sale_product_is_not_in_scope(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    foreign = await seed_product(database, MERCHANT_TWO_ID)
    offline = await seed_product(database, MERCHANT_ONE_ID, status="OFFLINE")
    headers = await _guest(postgres_client)

    bodies = []
    for target in (foreign, offline, uuid4(), "not-a-uuid"):
        resp = await _put(postgres_client, headers, target, 1)
        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "PRODUCT_NOT_IN_SCOPE"
        assert resp.json()["details"] == []
        bodies.append({k: v for k, v in resp.json().items() if k != "request_id"})

    assert all(body == bodies[0] for body in bodies)
    async with database.session() as session:
        lines = await session.scalar(select(func.count()).select_from(CartLine))
        audits = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.event_type == "RESOURCE_SCOPE_VIOLATION")
        )
    assert lines == 0
    assert audits == 4


@pytest.mark.asyncio
async def test_sold_out_product_cannot_be_added_but_can_be_removed(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=5)
    headers = await _guest(postgres_client)
    await _put(postgres_client, headers, pid, 1)
    await _set_product(database, pid, stock_reserved=5)

    add = await _put(postgres_client, headers, pid, 2)
    remove = await _put(postgres_client, headers, pid, 0)

    assert add.status_code == 409
    assert add.json()["code"] == "INSUFFICIENT_STOCK"
    assert remove.status_code == 200
    assert remove.json()["items"] == []


@pytest.mark.asyncio
async def test_cart_is_capped_at_fifty_lines(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    headers = await _guest(postgres_client)
    for _ in range(50):
        assert (
            await _put(postgres_client, headers, await seed_product(database, MERCHANT_ONE_ID), 1)
        ).status_code == 200

    extra = await _put(postgres_client, headers, await seed_product(database, MERCHANT_ONE_ID), 1)

    assert extra.status_code == 422
    assert extra.json()["code"] == "INVALID_REQUEST"
    assert len((await _cart(postgres_client, headers))["items"]) == 50


@pytest.mark.asyncio
async def test_delisted_line_stays_visible_as_out_of_stock(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """下架不静默删行：顾客能看到它不可买，提交订单时再明确报 DELISTED。"""

    database = _database(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID)
    headers = await _guest(postgres_client)
    await _put(postgres_client, headers, pid, 1)
    await _set_product(database, pid, status="OFFLINE")

    cart = await _cart(postgres_client, headers)

    assert [item["stock_band"] for item in cart["items"]] == ["OUT_OF_STOCK"]


@pytest.mark.asyncio
async def test_guest_carts_are_isolated(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    pid = await seed_product(_database(postgres_app), MERCHANT_ONE_ID)
    first = await _guest(postgres_client)
    second = await _guest(postgres_client)
    await _put(postgres_client, first, pid, 3)

    assert (await _cart(postgres_client, second))["items"] == []


@pytest.mark.asyncio
async def test_merchant_session_cannot_use_the_cart(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.get("/api/v2/shop/cart", headers=headers)

    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"


@pytest.mark.asyncio
async def test_cart_requires_a_session(postgres_client: AsyncClient) -> None:
    resp = await postgres_client.get("/api/v2/shop/cart")

    assert resp.status_code == 401
    assert resp.json()["code"] == "SESSION_REQUIRED"


# ---- 绑定时合并（D7⑥、PRD C3 / E9）---------------------------------------------


def test_production_wiring_no_longer_uses_empty_cart_merge() -> None:
    assert not isinstance(get_cart_merge_port(), EmptyCartMerge)


@pytest.mark.asyncio
async def test_bind_merges_guest_cart_once(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """同一会话重复绑定是幂等重绑：不再合并，数量不翻倍。"""

    _enable_demo_customer(postgres_app)
    pid = await seed_product(_database(postgres_app), MERCHANT_ONE_ID)
    guest = await _guest(postgres_client)
    await _put(postgres_client, guest, pid, 2)

    first = await _bind(postgres_client, guest)
    second = await _bind(postgres_client, guest)

    assert first["cart_adjusted"] is False and second["cart_adjusted"] is False
    assert _quantities(await _cart(postgres_client, guest)) == {str(pid): 2}


@pytest.mark.asyncio
async def test_rebinding_the_same_identity_restores_its_cart(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """刷新后新建访客会话、重新绑定同一演示身份，能取回自己的购物车并与新访客车相加。"""

    _enable_demo_customer(postgres_app)
    database = _database(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID)
    other = await seed_product(database, MERCHANT_ONE_ID)
    first = await _guest(postgres_client)
    await _put(postgres_client, first, pid, 2)
    await _bind(postgres_client, first)

    second = await _guest(postgres_client)
    await _put(postgres_client, second, pid, 3)
    await _put(postgres_client, second, other, 1)
    await _bind(postgres_client, second)

    expected = {str(pid): 5, str(other): 1}
    assert _quantities(await _cart(postgres_client, second)) == expected
    assert _quantities(await _cart(postgres_client, first)) == expected
    async with database.session() as session:
        guest_lines = await session.scalar(
            select(func.count()).select_from(CartLine).where(CartLine.buyer_key.is_(None))
        )
    assert guest_lines == 0  # 合并后清空访客购物车


@pytest.mark.asyncio
async def test_merge_sums_caps_and_drops_with_visible_adjustment(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """PRD C3 / E9：相加、99 截顶、剔除售罄，调整必须体现在 cart_adjusted。"""

    _enable_demo_customer(postgres_app)
    database = _database(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=500)
    sold_out_later = await seed_product(database, MERCHANT_ONE_ID, on_hand=5)
    owner = await _guest(postgres_client)
    await _put(postgres_client, owner, pid, 60)
    await _bind(postgres_client, owner)

    guest = await _guest(postgres_client)
    await _put(postgres_client, guest, pid, 50)
    await _put(postgres_client, guest, sold_out_later, 1)
    await _set_product(database, sold_out_later, stock_reserved=5)

    bound = await _bind(postgres_client, guest)

    assert bound["cart_adjusted"] is True
    assert _quantities(await _cart(postgres_client, guest)) == {str(pid): 99}


@pytest.mark.asyncio
async def test_merge_drops_delisted_guest_lines(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _enable_demo_customer(postgres_app)
    database = _database(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID)
    guest = await _guest(postgres_client)
    await _put(postgres_client, guest, pid, 1)
    await _set_product(database, pid, status="OFFLINE")

    bound = await _bind(postgres_client, guest)

    assert bound["cart_adjusted"] is True
    assert (await _cart(postgres_client, guest))["items"] == []


@pytest.mark.asyncio
async def test_merge_keeps_the_newest_fifty_lines(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _enable_demo_customer(postgres_app)
    database = _database(postgres_app)
    owner = await _guest(postgres_client)
    old_ids = [await seed_product(database, MERCHANT_ONE_ID) for _ in range(30)]
    for product_id in old_ids:
        await _put(postgres_client, owner, product_id, 1)
    await _bind(postgres_client, owner)
    # 已有购物车的加入时间整体推早一小时，让「最新」的判定不依赖同一毫秒内的插入顺序。
    async with database.session() as session:
        await session.execute(
            update(CartLine).values(created_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await session.commit()

    guest = await _guest(postgres_client)
    new_ids = [await seed_product(database, MERCHANT_ONE_ID) for _ in range(25)]
    for product_id in new_ids:
        await _put(postgres_client, guest, product_id, 1)

    bound = await _bind(postgres_client, guest)

    kept = set(_quantities(await _cart(postgres_client, guest)))
    assert bound["cart_adjusted"] is True
    assert len(kept) == 50
    assert {str(p) for p in new_ids} <= kept


@pytest.mark.asyncio
async def test_clean_merge_reports_no_adjustment(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _enable_demo_customer(postgres_app)
    pid = await seed_product(_database(postgres_app), MERCHANT_ONE_ID)
    guest = await _guest(postgres_client)
    await _put(postgres_client, guest, pid, 1)

    assert (await _bind(postgres_client, guest))["cart_adjusted"] is False
