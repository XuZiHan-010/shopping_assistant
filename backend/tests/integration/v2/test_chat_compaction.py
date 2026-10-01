"""压缩在两端 Chat 中对用户可见（N4-A Task 4，PRD A5，契约 §6.12 / §8.7.5）——全程 Fake LLM。

上下文超过 `COMPACTION_TRIGGER_TOKENS` 时压缩不静默发生：流式响应推送 `step` 事件，
最终响应（JSON 与 `turn_complete` 同一载荷）的 `thinking_steps` 记下这一步。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.agent.loop.compaction import COMPACTION_STEP_NODE
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from tests.conftest import MERCHANT_ONE_AUTH
from tests.support.merchant_v2 import merchant_session_headers
from tests.support.trade import SHOP

pytestmark = pytest.mark.integration

LONG_ANSWER = "上周整体平稳，各品类表现接近。" * 120  # 约 1800 字，超过 1000 的触发阈值


def _turn(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _compaction_settings(monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> None:
    settings = app.state.settings.model_copy(
        update={"compaction_strategy": "SUMMARIZATION", "compaction_trigger_tokens": 1_000}
    )
    monkeypatch.setattr(app.state, "settings", settings)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, turns: list[LlmTurn]) -> FakeLlmClient:
    fake = FakeLlmClient(turns=turns)
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    return fake


async def _first_turn(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v2/merchant/chat",
        json={"client_request_id": "cmp-1", "message": "上周怎么样"},
        headers={**headers, "Accept": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["thinking_steps"] == []  # 未超阈值：不压缩，不出现这一步
    return str(body["conversation_id"])


@pytest.mark.asyncio
async def test_compaction_is_listed_in_thinking_steps(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _compaction_settings(monkeypatch, postgres_app)
    fake = _patch_llm(
        monkeypatch, [_turn(LONG_ANSWER), _turn("商家在看上周经营。"), _turn("好的。")]
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    conversation_id = await _first_turn(postgres_client, headers)

    resp = await postgres_client.post(
        "/api/v2/merchant/chat",
        json={
            "client_request_id": "cmp-2",
            "message": "再说说",
            "conversation_id": conversation_id,
        },
        headers={**headers, "Accept": "application/json"},
    )

    assert resp.status_code == 200, resp.text
    steps = resp.json()["thinking_steps"]
    assert [s["node"] for s in steps] == [COMPACTION_STEP_NODE]
    assert steps[0]["label"] == "正在整理较早的对话"
    assert fake.converse_calls[1].tools == []  # 第二轮的第一次调用是摘要，不给工具
    assert LONG_ANSWER not in fake.converse_calls[2].messages[1].content


@pytest.mark.asyncio
async def test_compaction_streams_a_step_event(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _compaction_settings(monkeypatch, postgres_app)
    _patch_llm(monkeypatch, [_turn(LONG_ANSWER), _turn("商家在看上周经营。"), _turn("好的。")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    conversation_id = await _first_turn(postgres_client, headers)

    resp = await postgres_client.post(
        "/api/v2/merchant/chat",
        json={
            "client_request_id": "cmp-3",
            "message": "再说说",
            "conversation_id": conversation_id,
        },
        headers={**headers, "Accept": "text/event-stream"},
    )

    assert resp.status_code == 200, resp.text
    frames = [f for f in resp.text.split("\n\n") if f.startswith("event:")]
    names = [f.split("\n", 1)[0].removeprefix("event: ") for f in frames]
    assert names[0] == "step" and names[-1] == "turn_complete"
    step: dict[str, Any] = json.loads(frames[0].split("data: ", 1)[1])
    assert step == {"label": "正在整理较早的对话", "node": COMPACTION_STEP_NODE}
    final = json.loads(frames[-1].split("data: ", 1)[1])
    assert [s["node"] for s in final["thinking_steps"]] == [COMPACTION_STEP_NODE]


@pytest.mark.asyncio
async def test_shop_compaction_is_listed_in_thinking_steps(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _compaction_settings(monkeypatch, postgres_app)
    fake = FakeLlmClient(turns=[_turn(LONG_ANSWER), _turn("顾客在挑商品。"), _turn("好的。")])
    monkeypatch.setattr(
        "app.api.routes.v2.shop_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    session = await postgres_client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    assert session.status_code == 201, session.text
    headers = {"X-Session-Id": session.json()["session_id"], "Accept": "application/json"}

    first = await postgres_client.post(
        "/api/v2/shop/chat",
        json={"client_request_id": "shop-cmp-1", "message": "有什么推荐"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["thinking_steps"] == []
    second = await postgres_client.post(
        "/api/v2/shop/chat",
        json={
            "client_request_id": "shop-cmp-2",
            "message": "再说说",
            "conversation_id": first.json()["conversation_id"],
        },
        headers=headers,
    )

    assert second.status_code == 200, second.text
    assert [s["node"] for s in second.json()["thinking_steps"]] == [COMPACTION_STEP_NODE]
