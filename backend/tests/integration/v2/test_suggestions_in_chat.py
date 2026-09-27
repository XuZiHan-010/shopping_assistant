"""两端 Chat 响应携带「猜你想问」（PRD M13，契约 §8.7.10）——全程 Fake LLM。

要点：顾客端拿到的候选不含商家工具答得了的问题、反之亦然；语言随 `Accept-Language`；
建议随最终响应一起落盘，详情接口读回的 `answer` 逐字段相同。
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from httpx import AsyncClient

from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.services.v2.suggestions import (
    MERCHANT_ENTRY_POOLS,
    MERCHANT_FOLLOWUP_POOLS,
    SHOP_ENTRY_POOLS,
    SHOP_FOLLOWUP_POOLS,
)
from tests.conftest import MERCHANT_ONE_AUTH
from tests.support.merchant_v2 import merchant_session_headers
from tests.support.trade import SHOP

pytestmark = pytest.mark.integration

CJK = re.compile(r"[一-鿿]")
SHOP_TEXTS = {
    t
    for pools in (SHOP_ENTRY_POOLS, SHOP_FOLLOWUP_POOLS)
    for g in pools
    for i in g
    for t in (i.text, i.text_en)
}
MERCHANT_TEXTS = {
    t
    for pools in (MERCHANT_ENTRY_POOLS, MERCHANT_FOLLOWUP_POOLS)
    for g in pools
    for i in g
    for t in (i.text, i.text_en)
}


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _call(tool: str, call_id: str, **arguments: Any) -> LlmTurn:
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


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    module: str,
    turns: list[LlmTurn],
    *,
    configured: bool = True,
) -> None:
    fake = FakeLlmClient(turns=turns, configured=configured)
    monkeypatch.setattr(f"app.api.routes.v2.{module}.build_guarded_llm", lambda *a, **k: fake)


async def _guest(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    assert resp.status_code == 201, resp.text
    return {"X-Session-Id": resp.json()["session_id"]}


async def _post(
    client: AsyncClient,
    path: str,
    headers: dict[str, str],
    message: str,
    *,
    locale: str | None = None,
    crid: str = "sug-1",
) -> dict[str, Any]:
    extra = {"Accept": "application/json", **({"Accept-Language": locale} if locale else {})}
    resp = await client.post(
        path, json={"client_request_id": crid, "message": message}, headers={**headers, **extra}
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


@pytest.mark.asyncio
async def test_shop_chat_returns_customer_suggestions_only(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, "shop_chat", [_answer("你好，欢迎光临。")])
    guest = await _guest(postgres_client)

    body = await _post(postgres_client, "/api/v2/shop/chat", guest, "你好")

    assert len(body["suggestions"]) == 3
    assert set(body["suggestions"]) <= SHOP_TEXTS
    assert not set(body["suggestions"]) & MERCHANT_TEXTS
    assert body["suggestion_alternates"]
    assert all(g != body["suggestions"] for g in body["suggestion_alternates"])


@pytest.mark.asyncio
async def test_shop_suggestions_follow_the_display_language(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, "shop_chat", [_answer("Hello there.")])
    guest = await _guest(postgres_client)

    body = await _post(postgres_client, "/api/v2/shop/chat", guest, "hi", locale="en-US")

    assert body["suggestions"] and not any(CJK.search(t) for t in body["suggestions"])
    assert not any(CJK.search(t) for group in body["suggestion_alternates"] for t in group)


@pytest.mark.asyncio
async def test_a_turn_that_used_tools_gets_followups_not_entry_questions(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(
        monkeypatch,
        "shop_chat",
        [_call("search_products", "c1", query="围巾"), _answer("本店暂时没有找到相关商品。")],
    )
    guest = await _guest(postgres_client)

    body = await _post(postgres_client, "/api/v2/shop/chat", guest, "找围巾")

    followups = {i.text for g in SHOP_FOLLOWUP_POOLS for i in g}
    assert body["answer_mode"] == "SHOP_GUIDE"
    assert set(body["suggestions"]) <= followups


@pytest.mark.asyncio
async def test_merchant_chat_returns_merchant_suggestions_only(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, "merchant_chat", [_answer("你好，我可以帮你看库存。")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _post(postgres_client, "/api/v2/merchant/chat", headers, "你好")

    assert len(body["suggestions"]) == 3
    assert set(body["suggestions"]) <= MERCHANT_TEXTS
    assert not set(body["suggestions"]) & SHOP_TEXTS


@pytest.mark.asyncio
async def test_suggestions_survive_the_conversation_detail_round_trip(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, "shop_chat", [_answer("你好，欢迎光临。")])
    guest = await _guest(postgres_client)
    turn = await _post(postgres_client, "/api/v2/shop/chat", guest, "你好")

    detail = await postgres_client.get(
        f"/api/v2/shop/conversations/{turn['conversation_id']}", headers=guest
    )

    stored = detail.json()["messages"]["items"][1]["answer"]
    assert stored["suggestions"] == turn["suggestions"] != []
    assert stored["suggestion_alternates"] == turn["suggestion_alternates"]


@pytest.mark.asyncio
async def test_degraded_turn_still_carries_suggestions_and_stays_flagged(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型不可用时兜底回答照样给入口问题，但降级标记不能因此被冲掉（R7）。"""

    _patch(monkeypatch, "shop_chat", [], configured=False)
    guest = await _guest(postgres_client)

    body = await _post(postgres_client, "/api/v2/shop/chat", guest, "你好")

    assert body["degraded"] is True and body["degraded_reason"]
    assert body["suggestions"]
