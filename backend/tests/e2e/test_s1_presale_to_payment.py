"""场景 S1：售前导购到支付（PRD §12.2，交易计划 Task 7）——后端 E2E，全程 Fake LLM。

```text
顾客提问 → Agent 检索本店商品并对比 → 加购 → 结账摘要（展示用）
→ 顾客界面提交订单并占库 → 顾客界面模拟支付 → 订单事件出现「已支付」
```

每一步都断言数据库副作用：购物车行、占用量、订单三维状态、事件行。Agent 只走到加购为止——
提交订单与支付是界面动作（`client_request_id`），模型的工具面里根本没有这两个能力。
浏览器 E2E 在 `n2-shop-nextjs-app` 完成后补。
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.jobs.rebuild_projections import rebuild_projections
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from tests.conftest import MERCHANT_ONE_ID
from tests.support.merchant_v2 import seed_product
from tests.support.trade import (
    Stock,
    bound_customer,
    count_orders,
    database_of,
    fulfillment_events,
    inventory_events,
    set_product,
    stock,
)

pytestmark = pytest.mark.integration

JSON = {"Accept": "application/json"}


def _call(call_id: str, tool: str, **arguments: Any) -> LlmTurn:
    return LlmTurn(
        text="",
        tool_calls=[
            LlmToolCall(
                call_id=call_id,
                tool_name=tool,
                arguments_json=json.dumps(arguments, ensure_ascii=False),
            )
        ],
        stop_reason="TOOL_USE",
        tokens=10,
    )


@pytest.mark.asyncio
async def test_s1_presale_guidance_to_payment(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = database_of(postgres_app)
    wool = await seed_product(database, MERCHANT_ONE_ID, title="羊毛围巾", on_hand=30)
    cashmere = await seed_product(database, MERCHANT_ONE_ID, title="羊绒围巾", on_hand=12)
    await set_product(
        database,
        cashmere,
        price=Decimal("259.00"),
        attributes={"材质": {"value": "100% 羊绒", "source": "MERCHANT"}},
    )
    headers = await bound_customer(postgres_client, postgres_app, buyer_key="s1-buyer")

    # 1. 顾客提问 → Agent 检索本店商品、逐个看详情对比、加购一条。
    fake = FakeLlmClient(
        turns=[
            _call("c1", "search_products", query="围巾"),
            _call("c2", "get_product", product_id=str(wool), attributes=["材质"]),
            _call("c3", "get_product", product_id=str(cashmere), attributes=["材质"]),
            _call("c4", "set_cart_item", product_id=str(cashmere), quantity=1),
            LlmTurn(
                text="羊毛款商家没有写材质，羊绒款是 100% 羊绒；已把羊绒围巾加入购物车，"
                "请在页面上确认并提交订单。",
                tool_calls=[],
                stop_reason="END_TURN",
                tokens=10,
            ),
        ]
    )
    monkeypatch.setattr(
        "app.api.routes.v2.shop_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    chat = await postgres_client.post(
        "/api/v2/shop/chat",
        json={"client_request_id": "s1-chat", "message": "冬天想买条围巾，比较一下再帮我加一条"},
        headers={**headers, **JSON},
    )

    assert chat.status_code == 200, chat.text
    turn = chat.json()
    assert turn["answer_mode"] == "SHOP_GUIDE"
    assert [c["tool_name"] for c in turn["tool_calls"]] == [
        "search_products",
        "get_product",
        "get_product",
        "set_cart_item",
    ]
    # 副作用：购物车一行，不占库存，Agent 没有产生任何订单。
    assert await stock(database, cashmere) == Stock(on_hand=12, reserved=0)
    assert await count_orders(database) == 0

    # 2. 结账摘要（展示用）：界面读购物车，金额以后端为准。
    cart = (await postgres_client.get("/api/v2/shop/cart", headers=headers)).json()
    assert [(i["product_id"], i["quantity"]) for i in cart["items"]] == [(str(cashmere), 1)]
    assert cart["subtotal_cents"] == 25900

    # 3. 顾客界面提交订单：同一事务建单、占库、写「已下单」。
    placed = await postgres_client.post(
        "/api/v2/shop/orders", json={"client_request_id": "s1-order"}, headers=headers
    )
    assert placed.status_code == 201, placed.text
    order = placed.json()
    assert (order["payment_status"], order["fulfillment_status"], order["after_sale_status"]) == (
        "PENDING",
        "NOT_SHIPPED",
        "NONE",
    )
    assert order["total_cents"] == 25900
    assert await stock(database, cashmere) == Stock(on_hand=12, reserved=1)
    assert await fulfillment_events(database, order["id"]) == ["ORDER_PLACED"]
    assert (await postgres_client.get("/api/v2/shop/cart", headers=headers)).json()["items"] == []

    # 4. 顾客界面模拟支付：占用转实扣，出现「已支付」事件。
    paid = await postgres_client.post(
        f"/api/v2/shop/orders/{order['id']}/pay",
        json={"client_request_id": "s1-pay"},
        headers=headers,
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["payment_status"] == "PAID"
    assert await stock(database, cashmere) == Stock(on_hand=11, reserved=0)
    assert await inventory_events(database, cashmere) == [
        ("ORDER_RESERVE", 1),
        ("PAYMENT_DEDUCT", 1),
    ]

    # 5. 订单事件出现「已支付」（经顾客端事件端点读取）；投影可由事件重算且无漂移。
    events = (
        await postgres_client.get(f"/api/v2/shop/orders/{order['id']}/events", headers=headers)
    ).json()
    assert [e["event_type"] for e in events["items"]] == ["ORDER_PLACED", "PAYMENT_CONFIRMED"]
    async with database.session() as session:
        report = await rebuild_projections(session, merchant_id=MERCHANT_ONE_ID)
    assert report.mismatches == 0, report.drift
    # 另一件商品全程未被触碰。
    assert await stock(database, wool) == Stock(on_hand=30, reserved=0)
