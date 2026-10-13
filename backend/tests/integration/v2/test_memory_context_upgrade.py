"""双端 Chat 和召回工具的实际目录、预算、时间和去重行为。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.session import SessionContext, SessionRole
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from app.tools.types import ToolContext
from tests.api.v2.test_shop_memory import _session
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.memory_owners import CustomerStoreFor, MerchantStoreFor
from tests.support.merchant_v2 import merchant_session_headers
from tests.support.trade import database_of


@pytest.mark.parametrize("merchant", [False, True])
async def test_chat_exposes_old_category_without_loading_its_body(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    merchant: bool,
) -> None:
    now = datetime.now(UTC)
    database = database_of(postgres_app)
    async with database.session() as session:
        if merchant:
            store = MerchantStoreFor(session)
            old = await store.add_fact(
                merchant_id=MERCHANT_ONE_ID,
                category="old_tone",
                content="旧偏好正文",
                source_ref=f"{uuid4()}:{uuid4()}",
                at=now - timedelta(days=1),
            )
            for i in range(3):
                await store.add_fact(
                    merchant_id=MERCHANT_ONE_ID,
                    category=f"new_{i}",
                    content=f"近期偏好{i}",
                    source_ref=f"{uuid4()}:{uuid4()}",
                    at=now + timedelta(seconds=i),
                )
            await store.rebuild_summaries(merchant_id=MERCHANT_ONE_ID, at=now)
        else:
            store = CustomerStoreFor(session)
            old = await store.write(
                merchant_id=MERCHANT_ONE_ID,
                buyer_key="memory-buyer",
                category="sizing",
                key="fit",
                value="旧偏好正文",
                at=now - timedelta(days=1),
            )
            for i in range(3):
                await store.write(
                    merchant_id=MERCHANT_ONE_ID,
                    buyer_key="memory-buyer",
                    category="purchase",
                    key=f"packaging_{i}",
                    value=f"近期偏好{i}",
                    at=now + timedelta(seconds=i),
                )
        assert old is not None
        await session.commit()
    surface = "merchant" if merchant else "shop"
    fake = FakeLlmClient(
        turns=[LlmTurn(text="已了解", tool_calls=[], stop_reason="END_TURN", tokens=10)]
    )
    monkeypatch.setattr(f"app.api.routes.v2.{surface}_chat.build_guarded_llm", lambda *a, **k: fake)
    headers = (
        await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
        if merchant
        else await _session(postgres_client, postgres_app, bind=True)
    )
    response = await postgres_client.post(
        f"/api/v2/{surface}/chat",
        headers={**headers, "Accept": "application/json"},
        json={"message": "你好", "client_request_id": "memory-directory"},
    )
    assert response.status_code == 200, response.text
    prompt = fake.converse_calls[0].messages[0].content
    assert '"directory"' in prompt
    assert ("old_tone" if merchant else "sizing") in prompt
    assert "旧偏好正文" not in prompt
    assert prompt.count("近期偏好") == 3


@pytest.mark.parametrize("merchant", [False, True])
async def test_recall_excludes_loaded_ids_and_attaches_confirmation_time(
    postgres_app: FastAPI,
    merchant: bool,
) -> None:
    database = database_of(postgres_app)
    now = datetime.now(UTC)
    ids = []
    async with database.session() as session:
        for i in range(2):
            if merchant:
                row = await MerchantStoreFor(session).add_fact(
                    merchant_id=MERCHANT_ONE_ID,
                    category="presentation",
                    content=f"偏好{i}",
                    source_ref=f"{uuid4()}:{uuid4()}",
                    at=now,
                )
            else:
                row = await CustomerStoreFor(session).write(
                    merchant_id=MERCHANT_ONE_ID,
                    buyer_key="memory-buyer",
                    category="appearance",
                    key=f"key{i}",
                    value=f"偏好{i}",
                    at=now,
                )
            ids.append(str(row.id))
        await session.commit()
    from app.tools.customer.memory import build_memory_tools as customer_tools
    from app.tools.merchant.memory import build_memory_tools as merchant_tools

    spec = (merchant_tools(database) if merchant else customer_tools(database))[0]
    ctx = ToolContext(
        session=SessionContext(
            session_record_id=uuid4(),
            role=SessionRole.MERCHANT if merchant else SessionRole.CUSTOMER,
            merchant_id=MERCHANT_ONE_ID,
            buyer_key=None if merchant else "memory-buyer",
            shop_slug=None,
        ),
        conversation_id=str(uuid4()),
        request_id="memory-recall",
        memory_excluded_ids=(ids[0],),
    )
    result = await spec.executor(
        ctx, spec.args_model(category="presentation" if merchant else "appearance")
    )
    rows = result.payload["facts" if merchant else "memories"]
    assert [row["id"] for row in rows] == [ids[1]]
    assert rows[0]["last_confirmed_at"] == now.isoformat()
    repeated = await spec.executor(
        ctx, spec.args_model(category="presentation" if merchant else "appearance")
    )
    assert repeated.payload["facts" if merchant else "memories"] == []


async def test_customer_recall_reports_quantity_truncation(postgres_app: FastAPI) -> None:
    from app.tools.customer.memory import build_memory_tools

    database = database_of(postgres_app)
    async with database.session() as session:
        for i in range(6):
            await CustomerStoreFor(session).write(
                merchant_id=MERCHANT_ONE_ID,
                buyer_key="memory-buyer",
                category="appearance",
                key=f"key-{i}",
                value=f"偏好{i}",
                at=datetime.now(UTC),
            )
        await session.commit()
    spec = build_memory_tools(database)[0]
    ctx = ToolContext(
        session=SessionContext(
            session_record_id=uuid4(),
            role=SessionRole.CUSTOMER,
            merchant_id=MERCHANT_ONE_ID,
            buyer_key="memory-buyer",
            shop_slug=None,
        ),
        conversation_id=str(uuid4()),
        request_id="memory-limit",
    )
    result = await spec.executor(ctx, spec.args_model(category="appearance"))
    assert len(result.payload["memories"]) == 5
    assert result.payload["truncated"] is True
