"""W Task 3：商家订单只读面（契约 §8.12.4）——真实 PostgreSQL，经真实路由与会话。

复用 §8.10.1 `to_order_summary` / `to_order_detail` 与 `order_leads` / `last_event_times`；
本文件只验证商家侧新增内容：`buyer_alias`（与商家售后同一派生函数）、三项筛选、游标绑定筛选、
跨商家/历史订单的统一 403、以及价格快照与顾客端详情一致。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete, event, select, update

from app.core.session import buyer_alias
from app.db.session import Database
from app.models.analytics import Order, OrderItem
from app.models.operations import AuditLog
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product
from tests.support.trade import bound_customer, database_of

ORDERS = "/api/v2/merchant/orders"


@pytest.mark.asyncio
async def test_order_page_is_bounded_in_sql_and_bad_cursor_does_not_read_orders(
    postgres_app: FastAPI, postgres_client: AsyncClient,
) -> None:
    database = database_of(postgres_app)
    for _ in range(4):
        await _seed_order(database)
    headers = await _merchant_headers(postgres_client)
    statements: list[tuple[str, object]] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "FROM orders" in statement:
            statements.append((statement, parameters))

    event.listen(database.engine.sync_engine, "before_cursor_execute", record)
    try:
        response = await postgres_client.get(ORDERS, params={"limit": 2}, headers=headers)
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == 2
        assert response.json()["has_more"] is True
        assert statements
        assert all("LIMIT" in sql for sql, _ in statements)
        # SQL 驱动实际收到窗口上限 2 + 1，而不是把全店订单读入内存。
        assert any(3 in params.values() for _, params in statements)
        statements.clear()
        invalid = await postgres_client.get(
            ORDERS, params={"cursor": "tampered", "limit": 2}, headers=headers,
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "INVALID_CURSOR"
        assert statements == []
    finally:
        event.remove(database.engine.sync_engine, "before_cursor_execute", record)


@pytest.mark.asyncio
async def test_equal_timestamp_keyset_survives_deleted_anchor(
    postgres_app: FastAPI, postgres_client: AsyncClient,
) -> None:
    database = database_of(postgres_app)
    moment = datetime(2026, 9, 29, 12, 0, 0, 500000, tzinfo=UTC)
    ids = [(await _seed_order(database, now=moment))[0] for _ in range(5)]
    expected = sorted(map(str, ids), reverse=True)
    headers = await _merchant_headers(postgres_client)
    first = await postgres_client.get(ORDERS, params={"limit": 2}, headers=headers)
    assert first.status_code == 200, first.text
    assert [row["id"] for row in first.json()["items"]] == expected[:2]
    anchor = UUID(expected[1])
    async with database.session() as session:
        await session.execute(delete(OrderItem).where(OrderItem.order_id == anchor))
        await session.execute(delete(Order).where(Order.id == anchor))
        await session.commit()
    cursor = first.json()["next_cursor"]
    remaining: list[str] = []
    while cursor:
        response = await postgres_client.get(
            ORDERS, params={"limit": 2, "cursor": cursor}, headers=headers,
        )
        assert response.status_code == 200, response.text
        remaining.extend(row["id"] for row in response.json()["items"])
        cursor = response.json()["next_cursor"]
    assert remaining == expected[2:]

_DEV_BUYER_ALIAS_SECRET = b"development-buyer-alias-secret"


def _alias(merchant_id: UUID, buyer_key: str) -> str:
    return buyer_alias(_DEV_BUYER_ALIAS_SECRET, merchant_id, buyer_key)


async def _merchant_headers(client: AsyncClient) -> dict[str, str]:
    return await merchant_session_headers(client, MERCHANT_ONE_AUTH)


async def _seed_order(
    database: Database,
    merchant_id: UUID = MERCHANT_ONE_ID,
    *,
    buyer_key: str = "demo-buyer-1",
    quantity: int = 1,
    days_ago: int = 1,
    now: datetime | None = None,
) -> tuple[UUID, UUID]:
    moment = now or datetime.now(UTC)
    product_id = await seed_product(database, merchant_id, now=moment)
    order_id = await seed_paid_order(
        database, merchant_id, product_id, quantity=quantity, days_ago=days_ago, now=moment
    )
    if buyer_key != "demo-buyer-1":
        async with database.session() as session:
            await session.execute(
                update(Order).where(Order.id == order_id).values(buyer_key=buyer_key)
            )
            await session.commit()
    return order_id, product_id


@pytest.mark.asyncio
async def test_list_only_contains_this_merchants_v2_orders(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    mine, _ = await _seed_order(database)
    other, _ = await _seed_order(database, MERCHANT_TWO_ID)
    headers = await _merchant_headers(postgres_client)

    resp = await postgres_client.get(ORDERS, headers=headers)

    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(mine) in ids
    assert str(other) not in ids


@pytest.mark.asyncio
async def test_list_response_has_buyer_alias_matching_after_sales_and_no_buyer_key(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    order_id, _ = await _seed_order(database, buyer_key="alias-buyer")
    headers = await _merchant_headers(postgres_client)

    resp = await postgres_client.get(ORDERS, headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    item = next(i for i in body["items"] if i["id"] == str(order_id))
    assert item["buyer_alias"] == _alias(MERCHANT_ONE_ID, "alias-buyer")
    assert "buyer_key" not in str(body)


@pytest.mark.asyncio
async def test_each_filter_narrows_the_list(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    paid_order, _ = await _seed_order(database, days_ago=1)
    headers = await _merchant_headers(postgres_client)

    matching = await postgres_client.get(
        ORDERS, params={"payment_status": "PAID"}, headers=headers
    )
    non_matching = await postgres_client.get(
        ORDERS, params={"payment_status": "PENDING"}, headers=headers
    )
    fulfillment_match = await postgres_client.get(
        ORDERS, params={"fulfillment_status": "NOT_SHIPPED"}, headers=headers
    )
    after_sale_match = await postgres_client.get(
        ORDERS, params={"after_sale_status": "NONE"}, headers=headers
    )
    after_sale_non_match = await postgres_client.get(
        ORDERS, params={"after_sale_status": "ACTIVE"}, headers=headers
    )

    assert matching.status_code == 200, matching.text
    assert str(paid_order) in {i["id"] for i in matching.json()["items"]}
    assert str(paid_order) not in {i["id"] for i in non_matching.json()["items"]}
    assert str(paid_order) in {i["id"] for i in fulfillment_match.json()["items"]}
    assert str(paid_order) in {i["id"] for i in after_sale_match.json()["items"]}
    assert str(paid_order) not in {i["id"] for i in after_sale_non_match.json()["items"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filter_name", "minted_value", "changed_value"),
    [
        ("payment_status", "PAID", "PENDING"),
        ("fulfillment_status", "NOT_SHIPPED", "SHIPPED"),
        ("after_sale_status", "NONE", "ACTIVE"),
    ],
)
async def test_cursor_is_bound_to_each_filter_and_rejects_when_it_changes(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
    filter_name: str,
    minted_value: str,
    changed_value: str,
) -> None:
    """游标绑定三项筛选中的**每一项**；换其中任意一项都必须使旧游标失效（§8.7.4）。"""

    database = database_of(postgres_app)
    now = datetime.now(UTC)
    for index in range(3):
        await _seed_order(database, days_ago=1, now=now - timedelta(minutes=index))
    headers = await _merchant_headers(postgres_client)

    first = await postgres_client.get(
        ORDERS, params={"limit": 1, filter_name: minted_value}, headers=headers
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert cursor is not None

    same_filter = await postgres_client.get(
        ORDERS,
        params={"limit": 1, filter_name: minted_value, "cursor": cursor},
        headers=headers,
    )
    assert same_filter.status_code == 200, same_filter.text

    changed_filter = await postgres_client.get(
        ORDERS,
        params={"limit": 1, filter_name: changed_value, "cursor": cursor},
        headers=headers,
    )
    assert changed_filter.status_code == 422, changed_filter.text
    assert changed_filter.json()["code"] == "INVALID_CURSOR"

    dropped_filter = await postgres_client.get(
        ORDERS, params={"limit": 1, "cursor": cursor}, headers=headers
    )
    assert dropped_filter.status_code == 422, dropped_filter.text
    assert dropped_filter.json()["code"] == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_detail_price_snapshot_matches_customer_view(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    product_id = await seed_product(database, MERCHANT_ONE_ID)
    order_id = await seed_paid_order(
        database, MERCHANT_ONE_ID, product_id, quantity=2, days_ago=1
    )
    async with database.session() as session:
        await session.execute(
            update(Order).where(Order.id == order_id).values(buyer_key="snapshot-buyer")
        )
        await session.commit()

    customer_headers = await bound_customer(
        postgres_client, postgres_app, buyer_key="snapshot-buyer"
    )
    customer_detail = (
        await postgres_client.get(f"/api/v2/shop/orders/{order_id}", headers=customer_headers)
    ).json()

    merchant_headers = await _merchant_headers(postgres_client)
    merchant_detail = (
        await postgres_client.get(f"{ORDERS}/{order_id}", headers=merchant_headers)
    ).json()

    assert merchant_detail["items"] == customer_detail["items"]
    assert merchant_detail["total_cents"] == customer_detail["total_cents"]
    assert merchant_detail["subtotal_cents"] == customer_detail["subtotal_cents"]
    assert merchant_detail["buyer_alias"] == _alias(MERCHANT_ONE_ID, "snapshot-buyer")
    assert "buyer_key" not in str(merchant_detail)


@pytest.mark.asyncio
async def test_other_merchants_order_returns_resource_forbidden_and_audits(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    other_order, _ = await _seed_order(database, MERCHANT_TWO_ID)
    headers = await _merchant_headers(postgres_client)

    resp = await postgres_client.get(f"{ORDERS}/{other_order}", headers=headers)

    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"
    assert resp.json()["details"] == []
    async with database.session() as session:
        events = (
            await session.scalars(
                select(AuditLog.event_type).where(
                    AuditLog.event_type == "RESOURCE_SCOPE_VIOLATION"
                )
            )
        ).all()
    assert events


@pytest.mark.asyncio
async def test_historical_non_v2_order_returns_same_resource_forbidden(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    order_id, _ = await _seed_order(database)
    async with database.session() as session:
        await session.execute(
            update(Order).where(Order.id == order_id).values(lifecycle_origin="LEGACY_V1")
        )
        await session.commit()
    headers = await _merchant_headers(postgres_client)

    resp = await postgres_client.get(f"{ORDERS}/{order_id}", headers=headers)

    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_malformed_order_id_returns_same_resource_forbidden(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await _merchant_headers(postgres_client)

    resp = await postgres_client.get(f"{ORDERS}/not-a-uuid", headers=headers)

    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_list_and_detail_require_a_merchant_session(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    missing_list = await postgres_client.get(ORDERS)
    assert missing_list.status_code == 401

    created = await postgres_client.post(
        "/api/v2/shop/sessions", json={"shop_slug": "borough-api-100"}
    )
    customer_headers = {"X-Session-Id": created.json()["session_id"]}
    customer_list = await postgres_client.get(ORDERS, headers=customer_headers)
    assert customer_list.status_code == 403
    assert customer_list.json()["code"] == "SESSION_ROLE_MISMATCH"

    database = database_of(postgres_app)
    order_id, _ = await _seed_order(database)
    customer_detail = await postgres_client.get(
        f"{ORDERS}/{order_id}", headers=customer_headers
    )
    assert customer_detail.status_code == 403
    assert customer_detail.json()["code"] == "SESSION_ROLE_MISMATCH"
