"""`get_metric_definition`/`search_rules` 在真实商家 Chat 回合中的行为
（N3 阶段 C Task 6，PRD M8、S7，Astra N3-4 必审）。

全程 Fake LLM + 真实 PostgreSQL。核心断言：指标口径并列展示业务口径与 SQL 口径、
SQL 口径从不被执行、规则问答命中知识库文档并可引用。
"""

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

CHAT_PATH = "/api/v2/merchant/chat"
JSON_HEADERS = {"Accept": "application/json"}


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _call(tool: str, call_id: str, **arguments: object) -> LlmTurn:
    return LlmTurn(
        text="",
        tool_calls=[
            LlmToolCall(call_id=call_id, tool_name=tool, arguments_json=json.dumps(arguments))
        ],
        stop_reason="TOOL_USE",
        tokens=10,
    )


def _patch_llm(monkeypatch: pytest.MonkeyPatch, turns: list[LlmTurn]) -> FakeLlmClient:
    fake = FakeLlmClient(turns=turns)
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm",
        lambda *args, **kwargs: fake,
    )
    return fake


async def _seed_metric_definition(database: Database) -> None:
    async with database.session() as session:
        existing = (
            await session.execute(
                select(MetricDefinition).where(MetricDefinition.metric_code == "net_gmv")
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            MetricDefinition(
                metric_code="net_gmv",
                display_name="净成交额",
                unit="元",
                business_definition="毛成交额减去退款金额",
                sql_definition="gross_gmv - refund_amount",
                source="METRIC_CATALOG",
                owner="经营分析组",
                dimensions=["date"],
                source_database="public",
                source_table="orders",
                status="ACTIVE",
            )
        )
        await session.commit()


async def _seed_rule_document(database: Database) -> None:
    async with database.session() as session:
        existing = (
            await session.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.source_path == "平台规则/after_sale_freight.md"
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
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


@pytest.mark.asyncio
async def test_metric_definition_shows_both_calibers_and_sql_never_executed(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    await _seed_metric_definition(database)
    _patch_llm(
        monkeypatch,
        [
            _call("get_metric_definition", "c1", metric_code="net_gmv"),
            _answer("净成交额 = 毛成交额 - 退款金额，指标定义版本已确认。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "def-1", "message": "净成交额怎么算的"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(c["tool_name"] == "get_metric_definition" for c in body["tool_calls"])
    assert body["degraded"] is False


@pytest.mark.asyncio
async def test_unverified_metric_returns_status_without_llm_generation(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """脚本只安排了两轮：一次工具调用 + 一次最终作答；`FakeLlmClient` 的轮次列表
    用完即弹出（见 `app/llm/fake.py`），如果 `get_metric_definition` 未命中正式口径时
    静默触发了第三次"生成候选定义"的模型调用，脚本耗尽会导致请求直接失败，
    而不是悄悄多打一次真实/可能计费的 LLM 调用。"""

    _patch_llm(
        monkeypatch,
        [
            _call("get_metric_definition", "c1", metric_code="totally_unknown_metric"),
            _answer("这个指标目前没有正式口径，标注为待核验。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "def-2", "message": "totally_unknown_metric 怎么算的"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is False
    assert any(c["tool_name"] == "get_metric_definition" for c in body["tool_calls"])


@pytest.mark.asyncio
async def test_search_rules_finds_and_can_cite_document(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    await _seed_rule_document(database)
    _patch_llm(
        monkeypatch,
        [
            _call("search_rules", "c1", query="退货运费谁出"),
            _answer("根据平台规则，退货运费由平台承担，商家不需垫付。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "def-3", "message": "退货运费谁出"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is False
    assert any(c["tool_name"] == "search_rules" for c in body["tool_calls"])
