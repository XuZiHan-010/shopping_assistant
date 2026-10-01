"""商家记忆两层 API 的隔离、来源和删除语义。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from app.memory.merchant_store import MerchantMemoryStore
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_AUTH
from tests.support.merchant_v2 import merchant_session_headers

NOW = datetime(2026, 9, 28, tzinfo=UTC)


@pytest.mark.asyncio
async def test_merchant_lists_fact_and_summary_then_deletes_fact_idempotently(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database: Database = postgres_app.state.database
    source_conversation, source_message = uuid4(), uuid4()
    async with database.session() as session:
        store = MerchantMemoryStore(session)
        fact = await store.add_fact(
            merchant_id=MERCHANT_ONE_ID, category="tone", content="回复语气偏正式",
            source_ref=f"{source_conversation}:{source_message}", at=NOW,
        )
        assert fact is not None
        await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)
        fact_id = str(fact.id)
        await session.commit()
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    listed = await postgres_client.get("/api/v2/merchant/memories", headers=headers)
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["facts"]["items"][0]["source_ref"] == {
        "conversation_id": str(source_conversation), "message_id": str(source_message)
    }
    assert len(payload["summaries"]) == 1
    summary_id = payload["summaries"][0]["id"]
    rejected = await postgres_client.delete(
        f"/api/v2/merchant/memories/{summary_id}", headers=headers
    )
    assert rejected.status_code == 422
    deleted = await postgres_client.delete(
        f"/api/v2/merchant/memories/{fact_id}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted_id": fact_id, "summary_rebuild_scheduled": True}
    repeated = await postgres_client.delete(
        f"/api/v2/merchant/memories/{fact_id}", headers=headers
    )
    assert repeated.status_code == 200
    assert repeated.json()["summary_rebuild_scheduled"] is False
    after = await postgres_client.get("/api/v2/merchant/memories", headers=headers)
    assert after.json()["facts"]["items"] == []


@pytest.mark.asyncio
async def test_other_merchant_and_unknown_fact_have_same_public_error(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database: Database = postgres_app.state.database
    async with database.session() as session:
        fact = await MerchantMemoryStore(session).add_fact(
            merchant_id=MERCHANT_ONE_ID, category="tone", content="回复语气偏正式",
            source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
        )
        assert fact is not None
        foreign_id = str(fact.id)
        await session.commit()
    headers = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)
    foreign = await postgres_client.delete(
        f"/api/v2/merchant/memories/{foreign_id}", headers=headers
    )
    unknown = await postgres_client.delete(
        f"/api/v2/merchant/memories/{uuid4()}", headers=headers
    )
    assert foreign.status_code == unknown.status_code == 403
    assert foreign.json()["code"] == unknown.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_nonstale_merchant_memory_is_fenced_after_static_prompt(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database: Database = postgres_app.state.database
    async with database.session() as session:
        store = MerchantMemoryStore(session)
        await store.add_fact(
            merchant_id=MERCHANT_ONE_ID, category="tone", content="回复语气偏正式",
            source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
        )
        await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=NOW)
        await session.commit()
    fake = FakeLlmClient(turns=[
        LlmTurn(text="已收到", tool_calls=[], stop_reason="END_TURN", tokens=10)
    ])
    monkeypatch.setattr("app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *a, **k: fake)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    response = await postgres_client.post(
        "/api/v2/merchant/chat", headers={**headers, "Accept": "application/json"},
        json={"message": "你好", "client_request_id": "merchant-memory-prompt"},
    )
    assert response.status_code == 200, response.text
    prompt = fake.converse_calls[0].messages[0].content
    assert '<external-data source="merchant_memory"' in prompt
    assert "回复语气偏正式" in prompt


@pytest.mark.asyncio
async def test_memory_never_used_as_number_source(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M11：记忆只影响语气与呈现，回答里只在记忆中出现的数字判无来源并降级。"""

    database: Database = postgres_app.state.database
    async with database.session() as session:
        await MerchantMemoryStore(session).add_fact(
            merchant_id=MERCHANT_ONE_ID, category="context", content="上月净成交额大约 50 万",
            source_ref=f"{uuid4()}:{uuid4()}", at=NOW,
        )
        await session.commit()
    fake = FakeLlmClient(turns=[
        LlmTurn(text="上月净成交额是 50 万", tool_calls=[], stop_reason="END_TURN", tokens=10),
        LlmTurn(text="上月净成交额是 50 万", tool_calls=[], stop_reason="END_TURN", tokens=10),
    ])
    monkeypatch.setattr("app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *a, **k: fake)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    response = await postgres_client.post(
        "/api/v2/merchant/chat", headers={**headers, "Accept": "application/json"},
        json={"message": "上个月卖得怎么样", "client_request_id": "merchant-memory-number"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "上月净成交额大约 50 万" in fake.converse_calls[0].messages[0].content
    assert body["degraded"] is True
    assert "50 万" not in body["answer"]
