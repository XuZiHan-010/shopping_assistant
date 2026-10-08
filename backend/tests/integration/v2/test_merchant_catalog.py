"""商家商品内容与促销只读列表：确定性完整度、租户隔离和券状态。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.models.analytics import Product
from app.models.promotion import Coupon
from tests.conftest import (
    MERCHANT_ONE_AUTH,
    MERCHANT_ONE_ID,
    MERCHANT_TWO_AUTH,
    MERCHANT_TWO_ID,
)
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_merchant_product_content_lists_only_own_products_with_backend_missing_fields(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = postgres_app.state.database
    mine = await seed_product(database, MERCHANT_ONE_ID, title="待补资料连衣裙")
    other = await seed_product(database, MERCHANT_TWO_ID, title="其他商家商品")
    async with database.session() as session:
        product = await session.get(Product, mine)
        assert product is not None
        product.category = "女装"
        product.attributes = {"材质": {"value": "棉"}, "尺码": {"value": "M"}}
        await session.commit()

    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    response = await postgres_client.get("/api/v2/merchant/products/content", headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert any(
        item["id"] == str(mine)
        and item["missing_required_attributes"] == ["产地"]
        and item["missing_content_fields"] == ["商品图片", "商品描述"]
        and item["content_complete"] is False
        and item["stock_available"] == 40
        for item in items
    )
    assert all(item["id"] != str(other) for item in items)
    assert (await postgres_client.get("/api/v2/merchant/products/content")).status_code == 401


@pytest.mark.asyncio
async def test_merchant_product_content_returns_only_trusted_image_urls(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = postgres_app.state.database
    demo = await seed_product(
        database, MERCHANT_ONE_ID, title="有演示图", image_url="/demo/products/01.webp"
    )
    external = await seed_product(
        database, MERCHANT_ONE_ID, title="外部主机图", image_url="https://cdn.example.com/a.webp"
    )
    missing = await seed_product(database, MERCHANT_ONE_ID, title="无图")

    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    response = await postgres_client.get("/api/v2/merchant/products/content", headers=headers)
    assert response.status_code == 200, response.text
    images = {item["id"]: item["image_url"] for item in response.json()["items"]}
    assert images[str(demo)] == "/demo/products/01.webp"
    # 白名单为空：外部主机与顾客端一样不下发，不让商家端成为绕过图片白名单的出口。
    assert images[str(external)] is None
    assert images[str(missing)] is None


@pytest.mark.asyncio
async def test_merchant_coupons_include_inactive_own_coupons_without_other_tenant(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = postgres_app.state.database
    now = datetime.now(UTC)
    mine_id = uuid4()
    other_id = uuid4()
    async with database.session() as session:
        for coupon_id, merchant_id in (
            (mine_id, MERCHANT_ONE_ID),
            (other_id, MERCHANT_TWO_ID),
        ):
            session.add(
                Coupon(
                    id=coupon_id,
                    merchant_id=merchant_id,
                    name="九折券",
                    kind="DISCOUNT",
                    threshold_amount=Decimal("0.00"),
                    discount_amount=None,
                    discount_rate=Decimal("0.10"),
                    scope="SHOP",
                    product_ids=[],
                    starts_at=now - timedelta(days=1),
                    ends_at=now + timedelta(days=1),
                    state="INACTIVE",
                )
            )
        await session.commit()

    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    response = await postgres_client.get("/api/v2/merchant/coupons", headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert any(
        item["id"] == str(mine_id)
        and item["state"] == "INACTIVE"
        and item["discount_bps"] == 9000
        for item in items
    )
    assert all(item["id"] != str(other_id) for item in items)
    other_headers = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)
    other_response = await postgres_client.get("/api/v2/merchant/coupons", headers=other_headers)
    assert all(item["id"] != str(mine_id) for item in other_response.json()["items"])


@pytest.mark.asyncio
async def test_product_content_cursor_cannot_cross_merchants(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = postgres_app.state.database
    first = await seed_product(database, MERCHANT_ONE_ID, title="第一件")
    second = await seed_product(database, MERCHANT_ONE_ID, title="第二件")
    await seed_product(database, MERCHANT_TWO_ID, title="其他商家")
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    page = await postgres_client.get(
        "/api/v2/merchant/products/content?limit=1", headers=headers
    )
    assert page.status_code == 200
    assert page.json()["has_more"] is True
    cursor = page.json()["next_cursor"]
    next_page = await postgres_client.get(
        "/api/v2/merchant/products/content",
        params={"limit": 1, "cursor": cursor},
        headers=headers,
    )
    assert next_page.status_code == 200
    assert {page.json()["items"][0]["id"], next_page.json()["items"][0]["id"]} == {
        str(first), str(second)
    }
    other_headers = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)
    forbidden_cursor = await postgres_client.get(
        "/api/v2/merchant/products/content",
        params={"limit": 1, "cursor": cursor},
        headers=other_headers,
    )
    assert forbidden_cursor.status_code == 422
    assert forbidden_cursor.json()["code"] == "INVALID_CURSOR"
