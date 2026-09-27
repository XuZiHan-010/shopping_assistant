"""S6：滞销告警到促销券草稿、人工批准、顾客端可见的完整闭环。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import Database
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.drafts import Draft
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_s6_slow_moving_to_approved_coupon_visible_to_customer(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database: Database = postgres_app.state.database
    product_id = await seed_product(
        database, MERCHANT_ONE_ID, title="S6 滞销商品", on_hand=80, listed_days_ago=100
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    alerts = await postgres_client.get("/api/v2/merchant/inventory/alerts", headers=headers)
    assert alerts.status_code == 200
    assert any(
        item["product_id"] == str(product_id) and item["kind"] == "SLOW_MOVING"
        for item in alerts.json()["items"]
    )
    now = datetime.now(UTC)
    fake = FakeLlmClient(
        turns=[
            LlmTurn(
                text="",
                tool_calls=[
                    LlmToolCall(
                        call_id="c1",
                        tool_name="draft_coupon",
                        arguments_json=json.dumps(
                            {
                                "name": "S6 九折券",
                                "kind": "DISCOUNT",
                                "discount_rate": "0.10",
                                "product_ids": [str(product_id)],
                                "starts_at": (now - timedelta(minutes=1)).isoformat(),
                                "ends_at": (now + timedelta(days=7)).isoformat(),
                            }
                        ),
                    )
                ],
                stop_reason="TOOL_USE",
                tokens=10,
            ),
            LlmTurn(
                text="已起草促销券，请到审批页面确认。",
                tool_calls=[],
                stop_reason="END_TURN",
                tokens=10,
            ),
        ]
    )
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    chat = await postgres_client.post(
        "/api/v2/merchant/chat",
        json={"client_request_id": "s6-draft", "message": "给滞销商品起草九折券"},
        headers={**headers, "Accept": "application/json"},
    )
    assert chat.status_code == 200, chat.text
    assert any(call["tool_name"] == "draft_coupon" for call in chat.json()["tool_calls"])
    async with database.session() as session:
        draft = (
            await session.execute(select(Draft).where(Draft.merchant_id == MERCHANT_ONE_ID))
        ).scalar_one()
        draft_id: UUID = draft.id
        assert draft.state == "STAGED"
    before = await postgres_client.get("/api/v2/shop/stores/borough-api-100/coupons")
    assert before.status_code == 200
    assert all(item["name"] != "S6 九折券" for item in before.json()["items"])

    detail = await postgres_client.get(f"/api/v2/merchant/drafts/{draft_id}", headers=headers)
    assert detail.status_code == 200
    evidence = detail.json()["approval_evidence"]
    applied = await postgres_client.post(
        f"/api/v2/merchant/drafts/{draft_id}/apply",
        json={
            "client_request_id": "s6-approve",
            "draft_version": 1,
            "target_version": 0,
            "approval_evidence": evidence,
        },
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["draft"]["state"] == "APPLIED"
    after = await postgres_client.get("/api/v2/shop/stores/borough-api-100/coupons")
    assert after.status_code == 200
    assert any(
        item["name"] == "S6 九折券"
        and item["discount_bps"] == 9000
        and str(product_id) in item["product_ids"]
        for item in after.json()["items"]
    )
