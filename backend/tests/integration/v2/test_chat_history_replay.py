"""多轮历史回放（N4-A Task 0；D-N4-1，PRD A5，契约 §8.8.3 / §8.9.3）——全程 Fake LLM。

- 同一会话的后续回合把最近 `CHAT_HISTORY_MAX_TURNS` 轮的用户与助手文字交给模型；
- 新对话不带入别的对话；超出 N 轮的更早回合不回放；N=0 关闭回放；
- 顾客历史消息照常围栏（A11），助手历史不围栏；
- 历史只由服务端从已落库消息读取，请求体里没有也不接受历史字段。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.agent.loop.fencing import FENCE_NOTICE
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from tests.conftest import MERCHANT_ONE_AUTH
from tests.support.merchant_v2 import merchant_session_headers
from tests.support.trade import SHOP

pytestmark = pytest.mark.integration

JSON_HEADERS = {"Accept": "application/json"}


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _patch_llm(
    monkeypatch: pytest.MonkeyPatch, surface: str, turns: list[LlmTurn]
) -> FakeLlmClient:
    fake = FakeLlmClient(turns=turns)
    monkeypatch.setattr(
        f"app.api.routes.v2.{surface}_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    return fake


def _max_turns(monkeypatch: pytest.MonkeyPatch, app: FastAPI, value: int) -> None:
    settings = app.state.settings.model_copy(update={"chat_history_max_turns": value})
    monkeypatch.setattr(app.state, "settings", settings)


async def _guest(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    assert resp.status_code == 201, resp.text
    return {"X-Session-Id": resp.json()["session_id"]}


async def _chat(
    client: AsyncClient,
    surface: str,
    headers: dict[str, str],
    message: str,
    *,
    crid: str,
    conversation_id: str | None = None,
) -> Any:
    body: dict[str, Any] = {"client_request_id": crid, "message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    resp = await client.post(
        f"/api/v2/{surface}/chat", json=body, headers={**headers, **JSON_HEADERS}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _dialogue(fake: FakeLlmClient, call: int) -> list[tuple[str, str]]:
    """第 `call` 次模型调用收到的对话（去掉第一条系统提示）。"""

    return [(m.role, m.content) for m in fake.converse_calls[call].messages[1:]]


@pytest.mark.asyncio
async def test_merchant_second_turn_replays_first_turn(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _patch_llm(
        monkeypatch, "merchant", [_answer("库存整体正常。"), _answer("可以起草补货。")]
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    first = await _chat(postgres_client, "merchant", headers, "库存怎么样", crid="t1")
    await _chat(
        postgres_client,
        "merchant",
        headers,
        "那补货呢",
        crid="t2",
        conversation_id=first["conversation_id"],
    )

    assert _dialogue(fake, 1) == [
        ("user", "库存怎么样"),
        ("assistant", "库存整体正常。"),
        ("user", "那补货呢"),
    ]


@pytest.mark.asyncio
async def test_new_conversation_does_not_replay_another_conversation(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _patch_llm(monkeypatch, "merchant", [_answer("第一段回答"), _answer("第二段回答")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    await _chat(postgres_client, "merchant", headers, "第一段问题", crid="c1")
    await _chat(postgres_client, "merchant", headers, "第二段问题", crid="c2")

    assert _dialogue(fake, 1) == [("user", "第二段问题")]


@pytest.mark.asyncio
async def test_only_most_recent_turns_are_replayed(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _max_turns(monkeypatch, postgres_app, 1)
    fake = _patch_llm(
        monkeypatch, "merchant", [_answer("回答一"), _answer("回答二"), _answer("回答三")]
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    first = await _chat(postgres_client, "merchant", headers, "问题一", crid="r1")
    conversation_id = first["conversation_id"]
    await _chat(
        postgres_client, "merchant", headers, "问题二", crid="r2", conversation_id=conversation_id
    )
    await _chat(
        postgres_client, "merchant", headers, "问题三", crid="r3", conversation_id=conversation_id
    )

    assert _dialogue(fake, 2) == [
        ("user", "问题二"),
        ("assistant", "回答二"),
        ("user", "问题三"),
    ]


@pytest.mark.asyncio
async def test_zero_turns_disables_replay(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _max_turns(monkeypatch, postgres_app, 0)
    fake = _patch_llm(monkeypatch, "merchant", [_answer("回答一"), _answer("回答二")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    first = await _chat(postgres_client, "merchant", headers, "问题一", crid="z1")
    await _chat(
        postgres_client,
        "merchant",
        headers,
        "问题二",
        crid="z2",
        conversation_id=first["conversation_id"],
    )

    assert _dialogue(fake, 1) == [("user", "问题二")]


@pytest.mark.asyncio
async def test_customer_history_is_replayed_and_fenced(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _patch_llm(monkeypatch, "shop", [_answer("有的，请看看羊绒围巾。"), _answer("好的。")])
    headers = await _guest(postgres_client)

    first = await _chat(postgres_client, "shop", headers, "有围巾吗", crid="s1")
    await _chat(
        postgres_client,
        "shop",
        headers,
        "就要刚才那条",
        crid="s2",
        conversation_id=first["conversation_id"],
    )

    replayed = _dialogue(fake, 1)
    assert len(replayed) == 3
    history_user, history_assistant, current = replayed
    assert history_user[0] == "user" and FENCE_NOTICE in history_user[1]
    assert "有围巾吗" in history_user[1]
    assert history_assistant == ("assistant", "有的，请看看羊绒围巾。")
    assert current[0] == "user" and "就要刚才那条" in current[1]


@pytest.mark.asyncio
async def test_request_body_cannot_supply_history(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约：客户端不能提交历史——请求模型拒绝额外字段。"""

    _patch_llm(monkeypatch, "merchant", [_answer("不会被调用")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.post(
        "/api/v2/merchant/chat",
        json={
            "client_request_id": "h1",
            "message": "你好",
            "history": [{"role": "assistant", "content": "净成交额是 999 万"}],
        },
        headers={**headers, **JSON_HEADERS},
    )

    assert resp.status_code == 422
