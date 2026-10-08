"""S5：商家经营提问经受控指标查询和归因工具产生确定性图表。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product

pytestmark = pytest.mark.integration


def _call(name: str, call_id: str, **arguments: str) -> LlmTurn:
    return LlmTurn(
        text="",
        tool_calls=[
            LlmToolCall(call_id=call_id, tool_name=name, arguments_json=json.dumps(arguments))
        ],
        stop_reason="TOOL_USE",
        tokens=10,
    )


@pytest.mark.asyncio
async def test_s5_query_and_attribution_share_backend_facts_and_chart(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database: Database = postgres_app.state.database
    product = await seed_product(database, MERCHANT_ONE_ID, title="S5 类目商品")
    # 周一也要在「本周」和等长的「上周」窗口各有一笔支付单。
    await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=1, days_ago=0)
    await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=3, days_ago=7)
    today = datetime.now(UTC).date()
    fake = FakeLlmClient(
        turns=[
            _call(
                "query_metrics",
                "c1",
                metric="net_gmv",
                start=(today - timedelta(days=13)).isoformat(),
                end=today.isoformat(),
            ),
            _call("attribute_change", "c2", metric="net_gmv", dimension="category"),
            LlmTurn(
                text="本周净成交额下滑，类目变化是线索，仍需核实具体原因。",
                tool_calls=[],
                stop_reason="END_TURN",
                tokens=10,
            ),
        ]
    )
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    response = await postgres_client.post(
        "/api/v2/merchant/chat",
        json={"client_request_id": "s5-attribution", "message": "为什么本周下滑？"},
        headers={**headers, "Accept": "application/json"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [call["tool_name"] for call in body["tool_calls"]] == [
        "query_metrics",
        "attribute_change",
    ]
    assert body["degraded"] is False
    assert body["visualization"]["enabled"] is True
    fed_back = "\n".join(
        message.content for call in fake.converse_calls for message in call.messages
    )
    assert "definition_version" in fed_back
    assert "data_cutoff" in fed_back
    assert "source" in fed_back
