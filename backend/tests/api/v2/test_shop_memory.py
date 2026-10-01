"""N4 顾客记忆 API：绑定、双键隔离和关闭前确认。"""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from app.memory.customer_store import CustomerMemoryStore
from tests.conftest import MERCHANT_ONE_ID

SHOP = "borough-api-100"
NOW = datetime(2026, 9, 28, tzinfo=UTC)


async def _session(client: AsyncClient, app: FastAPI, *, bind: bool) -> dict[str, str]:
    app.state.settings.demo_deployment_mode = True
    app.state.settings.demo_customer_identities = {SHOP: "memory-buyer"}
    created = await client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    assert created.status_code == 201, created.text
    headers = {"X-Session-Id": created.json()["session_id"]}
    if bind:
        response = await client.post(
            "/api/v2/shop/sessions/demo-customer", json={}, headers=headers
        )
        assert response.status_code == 200, response.text
    return headers


@pytest.mark.asyncio
async def test_guest_cannot_list_memories(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await _session(postgres_client, postgres_app, bind=False)
    response = await postgres_client.get("/api/v2/shop/memories", headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "CUSTOMER_BINDING_REQUIRED"


@pytest.mark.asyncio
async def test_bound_customer_can_list_and_delete_memory(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await _session(postgres_client, postgres_app, bind=True)
    database: Database = postgres_app.state.database
    async with database.session() as session:
        memory = await CustomerMemoryStore(session).write(
            merchant_id=MERCHANT_ONE_ID, buyer_key="memory-buyer",
            category="preference", key="color", value="blue", at=NOW,
        )
        assert memory is not None
        memory_id = str(memory.id)
        await session.commit()
    listed = await postgres_client.get("/api/v2/shop/memories", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["memories"]["items"][0]["id"] == memory_id
    assert "buyer_key" not in listed.text and "merchant_id" not in listed.text
    assert "memory-buyer" not in listed.text and str(MERCHANT_ONE_ID) not in listed.text
    deleted = await postgres_client.delete(
        f"/api/v2/shop/memories/{memory_id}", headers=headers
    )
    assert deleted.status_code == 204, deleted.text
    assert (await postgres_client.get("/api/v2/shop/memories", headers=headers)).json()[
        "memories"
    ]["items"] == []


@pytest.mark.asyncio
async def test_disabling_memory_requires_confirmation_and_purges(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await _session(postgres_client, postgres_app, bind=True)
    missing = await postgres_client.put(
        "/api/v2/shop/memory-preference", json={"enabled": False}, headers=headers
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "CONFIRMATION_REQUIRED"
    confirmed = await postgres_client.put(
        "/api/v2/shop/memory-preference",
        json={"enabled": False, "purge_confirmation": "yes"}, headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["memory_enabled"] is False


@pytest.mark.asyncio
async def test_recent_memory_is_fenced_after_static_prompt(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = await _session(postgres_client, postgres_app, bind=True)
    database: Database = postgres_app.state.database
    async with database.session() as session:
        await CustomerMemoryStore(session).write(
            merchant_id=MERCHANT_ONE_ID, buyer_key="memory-buyer",
            category="preference", key="color", value="blue", at=NOW,
        )
        await session.commit()
    fake = FakeLlmClient(turns=[
        LlmTurn(text="这次按红色查找", tool_calls=[], stop_reason="END_TURN", tokens=10)
    ])
    monkeypatch.setattr("app.api.routes.v2.shop_chat.build_guarded_llm", lambda *a, **k: fake)
    response = await postgres_client.post(
        "/api/v2/shop/chat", headers={**headers, "Accept": "application/json"},
        json={"message": "这次想要红色", "client_request_id": "memory-prompt"},
    )
    assert response.status_code == 200, response.text
    assert fake.converse_calls
    prompt = fake.converse_calls[0].messages[0].content
    assert '<external-data source="customer_memory"' in prompt and "blue" in prompt
    assert prompt.index("可用 Skill") < prompt.index('<external-data source="customer_memory"')


@pytest.mark.asyncio
async def test_memory_number_is_not_a_price_source(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """记忆是默认值不是事实：只凭记忆复述的价格判无来源并降级（C7、A6）。"""

    headers = await _session(postgres_client, postgres_app, bind=True)
    database: Database = postgres_app.state.database
    async with database.session() as session:
        await CustomerMemoryStore(session).write(
            merchant_id=MERCHANT_ONE_ID, buyer_key="memory-buyer",
            category="preference", key="last_price", value="上次买的靴子 699 元", at=NOW,
        )
        await session.commit()
    fake = FakeLlmClient(turns=[
        LlmTurn(text="这双靴子 699 元", tool_calls=[], stop_reason="END_TURN", tokens=10),
        LlmTurn(text="这双靴子 699 元", tool_calls=[], stop_reason="END_TURN", tokens=10),
    ])
    monkeypatch.setattr("app.api.routes.v2.shop_chat.build_guarded_llm", lambda *a, **k: fake)

    response = await postgres_client.post(
        "/api/v2/shop/chat", headers={**headers, "Accept": "application/json"},
        json={"message": "那双靴子现在多少钱", "client_request_id": "memory-price"},
    )

    assert response.status_code == 200, response.text
    assert "699" in fake.converse_calls[0].messages[0].content
    assert response.json()["degraded"] is True
