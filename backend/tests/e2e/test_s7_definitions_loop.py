"""S7：商家在同一工作台回合核对指标口径和平台规则引用。"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import Database
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.knowledge import KnowledgeDocument, MetricDefinition
from tests.conftest import MERCHANT_ONE_AUTH
from tests.support.merchant_v2 import merchant_session_headers

pytestmark = pytest.mark.integration


async def _seed_assets(database: Database) -> None:
    async with database.session() as session:
        metric = await session.scalar(
            select(MetricDefinition).where(MetricDefinition.metric_code == "net_gmv")
        )
        if metric is None:
            session.add(
                MetricDefinition(
                    metric_code="net_gmv",
                    display_name="净成交额",
                    unit="元",
                    business_definition="当期毛成交额减去当期退款金额",
                    sql_definition="gross_gmv - refund_amount",
                    source="METRIC_CATALOG",
                    owner="经营分析组",
                    dimensions=["date"],
                    source_database="public",
                    source_table="orders",
                    status="ACTIVE",
                )
            )
        document = await session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.source_path == "平台规则/after_sale_freight.md"
            )
        )
        if document is None:
            session.add(
                KnowledgeDocument(
                    category="PLATFORM_RULE",
                    title="售后运费规则",
                    content="退货运费由平台承担，商家不需垫付。",
                    source="wiki",
                    source_path="平台规则/after_sale_freight.md",
                    is_complete=True,
                    status="ACTIVE",
                    source_locale="zh-CN",
                )
            )
        await session.commit()


def _call(name: str, call_id: str, **arguments: str) -> LlmTurn:
    return LlmTurn(
        text="",
        stop_reason="TOOL_USE",
        tokens=10,
        tool_calls=[
            LlmToolCall(call_id=call_id, tool_name=name, arguments_json=json.dumps(arguments))
        ],
    )


@pytest.mark.asyncio
async def test_s7_metric_definition_version_and_rule_citation(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_assets(postgres_app.state.database)
    fake = FakeLlmClient(
        turns=[
            _call("get_metric_definition", "c1", metric_code="net_gmv"),
            _call("search_rules", "c2", query="退货运费谁出"),
            LlmTurn(
                text="净成交额按正式口径计算；退货运费由平台承担。来源：平台规则/after_sale_freight.md。",
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
        json={
            "client_request_id": "s7-definition-rule",
            "message": "净成交额怎么算，退货运费谁出？",
        },
        headers={**headers, "Accept": "application/json"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [call["tool_name"] for call in body["tool_calls"]] == [
        "get_metric_definition",
        "search_rules",
    ]
    assert body["degraded"] is False
    assert "平台规则/after_sale_freight.md" in body["answer"]
    fed_back = "\n".join(
        message.content for call in fake.converse_calls for message in call.messages
    )
    assert "definition_version" in fed_back
    assert "source_path" in fed_back
    assert "gross_gmv - refund_amount" in fed_back
