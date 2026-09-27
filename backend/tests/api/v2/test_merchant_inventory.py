"""库存告警端点（PRD M5，契约 §8.12.3）：`GET /api/v2/merchant/inventory/alerts`。

真实 PostgreSQL：商家隔离、销量口径与游标绑定都只有在真库上跑才算数。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_AUTH, MERCHANT_TWO_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product

ALERTS_PATH = "/api/v2/merchant/inventory/alerts"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _alerts(client: AsyncClient, headers: dict[str, str], **params: Any) -> Any:
    resp = await client.get(ALERTS_PATH, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_alerts_are_merchant_scoped(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """R5：商家只看得到自己店铺的商品，别人的低库存商品不出现。"""

    database = _database(postgres_app)
    mine = await seed_product(database, MERCHANT_ONE_ID, title="我的商品", on_hand=2)
    theirs = await seed_product(database, MERCHANT_TWO_ID, title="别人的商品", on_hand=2)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _alerts(postgres_client, headers)

    ids = {item["product_id"] for item in body["items"]}
    assert str(mine) in ids
    assert str(theirs) not in ids


@pytest.mark.asyncio
async def test_alerts_are_sorted_by_severity_then_product(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, title="低库存", on_hand=3)
    await seed_product(database, MERCHANT_ONE_ID, title="售罄", on_hand=0)
    slow = await seed_product(database, MERCHANT_ONE_ID, title="滞销", on_hand=80)
    await seed_paid_order(database, MERCHANT_ONE_ID, slow, quantity=1, days_ago=3)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _alerts(postgres_client, headers)

    assert [item["kind"] for item in body["items"]] == [
        "OUT_OF_STOCK",
        "LOW_STOCK",
        "SLOW_MOVING",
    ]


@pytest.mark.asyncio
async def test_sales_window_only_counts_paid_orders_in_scope(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """销量由订单明细计算：窗口外的订单不计入，也不会泄漏到别的商品。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=4)
    await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=6, days_ago=3)
    await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=99, days_ago=60)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _alerts(postgres_client, headers)

    alert = next(item for item in body["items"] if item["product_id"] == str(product))
    assert alert["sold_last_30d"] == 6
    assert alert["days_of_supply"] == 20


@pytest.mark.asyncio
async def test_zero_sales_reports_unknown_days_of_supply(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=3)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _alerts(postgres_client, headers)

    alert = next(item for item in body["items"] if item["product_id"] == str(product))
    assert alert["sold_last_30d"] == 0
    assert alert["days_of_supply"] is None


@pytest.mark.asyncio
async def test_kind_filter_narrows_results(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    low = await seed_product(database, MERCHANT_ONE_ID, on_hand=3)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _alerts(postgres_client, headers, kind="LOW_STOCK")

    assert [item["product_id"] for item in body["items"]] == [str(low)]


@pytest.mark.asyncio
async def test_cursor_pages_do_not_repeat_or_drop_items(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    for index in range(5):
        await seed_product(database, MERCHANT_ONE_ID, title=f"缺货{index}", on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    first = await _alerts(postgres_client, headers, limit=2)
    assert first["has_more"] is True and first["next_cursor"]
    second = await _alerts(postgres_client, headers, limit=2, cursor=first["next_cursor"])
    third = await _alerts(postgres_client, headers, limit=2, cursor=second["next_cursor"])

    seen = [item["id"] for page in (first, second, third) for item in page["items"]]
    assert len(seen) == len(set(seen)) == 5
    assert third["has_more"] is False and third["next_cursor"] is None


@pytest.mark.asyncio
async def test_cursor_from_another_merchant_is_rejected(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """§8.7.4：游标绑定主体，换一个商家拿来用只能 422，不能返回数据。"""

    database = _database(postgres_app)
    for index in range(3):
        await seed_product(database, MERCHANT_ONE_ID, title=f"甲{index}", on_hand=0)
        await seed_product(database, MERCHANT_TWO_ID, title=f"乙{index}", on_hand=0)
    mine = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    theirs = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)
    first = await _alerts(postgres_client, mine, limit=1)

    resp = await postgres_client.get(
        ALERTS_PATH, headers=theirs, params={"limit": 1, "cursor": first["next_cursor"]}
    )

    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "INVALID_CURSOR"
    assert body["retryable"] is False


@pytest.mark.asyncio
async def test_cursor_is_bound_to_the_query_shape(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    for index in range(3):
        await seed_product(database, MERCHANT_ONE_ID, title=f"缺货{index}", on_hand=0)
        await seed_product(database, MERCHANT_ONE_ID, title=f"低库存{index}", on_hand=2)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    first = await _alerts(postgres_client, headers, limit=1)

    resp = await postgres_client.get(
        ALERTS_PATH,
        headers=headers,
        params={"limit": 1, "kind": "LOW_STOCK", "cursor": first["next_cursor"]},
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_alerts_require_a_merchant_session(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    missing = await postgres_client.get(ALERTS_PATH)
    assert missing.status_code == 401
    assert missing.json()["code"] == "SESSION_REQUIRED"

    invalid = await postgres_client.get(ALERTS_PATH, headers={"X-Session-Id": "not-a-session"})
    assert invalid.status_code == 401
    assert invalid.json()["code"] == "SESSION_INVALID"


@pytest.mark.asyncio
async def test_customer_session_cannot_read_merchant_alerts(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """跨角色访问一律 403（§8.7.1）。"""

    created = await postgres_client.post(
        "/api/v2/shop/sessions", json={"shop_slug": "borough-api-100"}
    )
    assert created.status_code == 201, created.text

    resp = await postgres_client.get(
        ALERTS_PATH, headers={"X-Session-Id": created.json()["session_id"]}
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"
