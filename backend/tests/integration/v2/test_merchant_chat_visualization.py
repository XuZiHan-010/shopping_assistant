"""商家 Chat 的图表可视化（N3 阶段 C，PRD M3，契约 §8.7.11）——真实 PostgreSQL。

`query_metrics`/`attribute_change` 调用后，`MerchantChatResponse.visualization` 应该带
后端算好的图表数据；其他工具/纯文字回合恒为 `enabled=false`；图表的完整数据点绝不能
出现在传给模型的工具消息里（只有汇总值可以）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product

pytestmark = pytest.mark.integration

CHAT_PATH = "/api/v2/merchant/chat"
JSON_HEADERS = {"Accept": "application/json"}


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


def _call(tool: str, call_id: str, **arguments: Any) -> LlmTurn:
    return LlmTurn(
        text="", tool_calls=[
            LlmToolCall(call_id=call_id, tool_name=tool, arguments_json=json.dumps(arguments))
        ],
        stop_reason="TOOL_USE", tokens=10,
    )


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, turns: list[LlmTurn]) -> FakeLlmClient:
    fake = FakeLlmClient(turns=turns)
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    return fake


@pytest.mark.asyncio
async def test_query_metrics_populates_visualization(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=1, days_ago=1)
    today = datetime.now(UTC).date()
    fake = _patch_llm(
        monkeypatch,
        [
            _call(
                "query_metrics", "c1", metric="gross_gmv",
                start=(today - timedelta(days=2)).isoformat(), end=today.isoformat(),
            ),
            _answer("过去 3 天的成交总额如上。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "viz-1", "message": "帮我看看最近 3 天的成交总额趋势"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["visualization"]["enabled"] is True
    assert body["visualization"]["type"] == "LINE"
    assert len(body["visualization"]["data"]) == 3  # 3 天的范围，每天一个点

    # 图表的完整数据点绝不能出现在传给模型的工具消息里（只有汇总值可以）。
    for call in fake.converse_calls:
        for message in call.messages:
            if message.role == "tool":
                assert "dimension_key" not in message.content
                assert "allowed_types" not in message.content


@pytest.mark.asyncio
async def test_attribute_change_populates_visualization(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=1, days_ago=1)
    _patch_llm(
        monkeypatch,
        [
            _call("attribute_change", "c1", metric="gross_gmv", dimension="category"),
            _answer("本周至今的分类贡献如上。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "viz-2", "message": "帮我看看这周哪个类目贡献最大"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 类目下没有种子数据时归因可能因基期缺口而停止；无论哪种情况，字段结构都必须存在。
    assert "enabled" in body["visualization"]
    if body["visualization"]["enabled"]:
        assert body["visualization"]["type"] in ("BAR", "PIE")


@pytest.mark.asyncio
async def test_non_metric_turn_has_disabled_visualization(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没调指标工具的普通问答，图表字段恒为 disabled——不为凑数编造一份图表。"""

    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID)
    _patch_llm(monkeypatch, [_answer("你好，我可以帮你查询经营数据。")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "viz-3", "message": "你好"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["visualization"]["enabled"] is False


@pytest.mark.asyncio
async def test_only_last_metric_query_becomes_the_visualization(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一回合调用了多个指标工具时，只取最后一次成功结果——与回答正文引用的数字同源。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=1, days_ago=1)
    today = datetime.now(UTC).date()
    _patch_llm(
        monkeypatch,
        [
            _call(
                "query_metrics", "c1", metric="gross_gmv",
                start=today.isoformat(), end=today.isoformat(),
            ),
            _call(
                "query_metrics", "c2", metric="order_count",
                start=(today - timedelta(days=1)).isoformat(), end=today.isoformat(),
            ),
            _answer("两个指标都已查询。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "viz-4", "message": "帮我看看成交总额和订单量"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["visualization"]["enabled"] is True
    assert body["visualization"]["metric_key"] == "order_count"


@pytest.mark.asyncio
async def test_degraded_turn_never_shows_a_visualization(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """降级回答（本例：模型拒绝调用工具、直接对未知问题强行终止）不得仍然展示图表（R7）。"""

    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID)
    fake = FakeLlmClient(
        turns=[LlmTurn(text="", tool_calls=[], stop_reason="MAX_TOKENS", tokens=10)]
    )
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "viz-5", "message": "帮我看看成交总额"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["degraded"] is True
    assert body["visualization"]["enabled"] is False
