"""场景 S3：库存告警闭环（PRD M5、M10，草稿计划 Task 8）——后端 E2E，全程 Fake LLM。

```text
顾客支付订单 → 可售降到阈值以下 → 最小简报出现低库存条目
→ 商家 Agent 起草补货 → 商家在审批界面批准 → 应用时校验当前在库量
→ 顾客端该商品库存档位从 LOW 恢复为 IN_STOCK
```

批准环节走真实审批证据签发与消费（§8.7.9），不是直接改库存的捷径——Agent 只能起草，
证据只从 `GET /drafts/{id}` 签发，聊天里的"批准"不生效（D9①）。最后一步专门经
**顾客端公开浏览接口**读档位，不直接查库：证明两端共享同一份库存事实，不是各自维护状态。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.jobs.rebuild_projections import rebuild_projections
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.drafts import Draft
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_product
from tests.support.trade import SHOP, Stock, bound_customer, database_of, put_cart, stock

pytestmark = pytest.mark.integration

JSON = {"Accept": "application/json"}
CHAT_PATH = "/api/v2/merchant/chat"
DRAFTS_PATH = "/api/v2/merchant/drafts"
LOW_STOCK_THRESHOLD = 5


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


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


async def _stock_band(client: AsyncClient, product_id: UUID) -> str:
    """只经顾客端公开浏览接口读档位，不直接查库（两端共享同一份库存事实的证明）。"""

    resp = await client.get(f"/api/v2/shop/stores/{SHOP}/products/{product_id}")
    assert resp.status_code == 200, resp.text
    return str(resp.json()["stock_band"])


@pytest.mark.asyncio
async def test_s3_low_stock_to_restock_and_stock_band_recovery(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = database_of(postgres_app)
    product = await seed_product(
        database,
        MERCHANT_ONE_ID,
        title="库存告警测试商品",
        on_hand=10,
        low_stock_threshold=LOW_STOCK_THRESHOLD,
    )
    assert await _stock_band(postgres_client, product) == "IN_STOCK"

    # 1. 顾客界面下单并支付，把可售量压到阈值以下（真实占库、真实实扣，不走捷径）。
    customer_headers = await bound_customer(postgres_client, postgres_app, buyer_key="s3-buyer")
    await put_cart(postgres_client, customer_headers, product, 6)
    placed = await postgres_client.post(
        "/api/v2/shop/orders", json={"client_request_id": "s3-order"}, headers=customer_headers
    )
    assert placed.status_code == 201, placed.text
    order_id = placed.json()["id"]
    assert await stock(database, product) == Stock(on_hand=10, reserved=6)

    paid = await postgres_client.post(
        f"/api/v2/shop/orders/{order_id}/pay",
        json={"client_request_id": "s3-pay"},
        headers=customer_headers,
    )
    assert paid.status_code == 200, paid.text
    assert await stock(database, product) == Stock(on_hand=4, reserved=0)  # 可售 4 ≤ 阈值 5

    # 2. 可售降到阈值以下：顾客端档位与商家端最小简报同时反映出来。
    assert await _stock_band(postgres_client, product) == "LOW_STOCK"

    merchant_headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    brief = (
        await postgres_client.get(
            "/api/v2/merchant/briefs/daily/current", headers=merchant_headers
        )
    ).json()
    alert_items = [item for item in brief["items"] if item["kind"] == "INVENTORY_ALERT"]
    assert any(
        str(product) in item["evidence"] and "库存偏低" in item["title"] for item in alert_items
    )

    # 3. 商家 Agent 起草补货：先看告警（来源闸门产出这个商品的引用），再起草——
    #    工具只写 `drafts` 表，起草不改库存。
    fake = FakeLlmClient(
        turns=[
            _call("c1", "get_inventory_alerts"),
            _call("c2", "draft_restock", product_id=str(product), delta=60),
            _answer("已为你起草补货草稿，请到审批界面批准。"),
        ]
    )
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    chat = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "s3-chat", "message": "这个商品库存告急，帮我起草补货"},
        headers={**merchant_headers, **JSON},
    )
    assert chat.status_code == 200, chat.text
    assert [c["tool_name"] for c in chat.json()["tool_calls"]] == [
        "get_inventory_alerts",
        "draft_restock",
    ]
    assert await stock(database, product) == Stock(on_hand=4, reserved=0)
    async with database.session() as session:
        draft = (
            (await session.execute(select(Draft).where(Draft.merchant_id == MERCHANT_ONE_ID)))
            .scalars()
            .one()
        )
    assert draft.state == "STAGED"
    assert draft.payload["delta"] == 60 and draft.payload["base_on_hand"] == 4

    # 4. 商家在审批界面批准：证据只从 `GET /drafts/{id}` 签发，Agent 拿不到（D9①）。
    detail = await postgres_client.get(f"{DRAFTS_PATH}/{draft.id}", headers=merchant_headers)
    assert detail.status_code == 200, detail.text
    evidence = detail.json()["approval_evidence"]
    assert evidence

    applied = await postgres_client.post(
        f"{DRAFTS_PATH}/{draft.id}/apply",
        json={
            "client_request_id": "s3-apply",
            "draft_version": draft.draft_version,
            "target_version": 4,
            "approval_evidence": evidence,
        },
        headers=merchant_headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["draft"]["state"] == "APPLIED"

    # 5. 应用时校验当前在库量恰好等于起草时的基数，库存原子加回。
    assert await stock(database, product) == Stock(on_hand=64, reserved=0)

    # 6. 顾客端该商品库存档位从 LOW 恢复为 IN_STOCK——经公开浏览接口断言，
    #    证明两端共享同一份库存事实，不是各自维护状态。
    assert await _stock_band(postgres_client, product) == "IN_STOCK"

    async with database.session() as session:
        report = await rebuild_projections(session, merchant_id=MERCHANT_ONE_ID)
    assert report.mismatches == 0, report.drift
