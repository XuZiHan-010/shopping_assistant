"""双端会话目录（N2 模块 D Task 1，契约 §8.8.2 / §8.9.2）——全程 Fake LLM。

最要紧的几条：
- 列表只含当前主体的对话：顾客按「本店 + 登录主体」，商家按本店且不含顾客对话；
- 不存在与不属于当前主体的详情 / 删除逐字段一致（403 RESOURCE_FORBIDDEN，空 details）；
- 删除后再次请求统一 403，同事务删除该对话的来源状态（O2）；删除的对话不能被续写；
- 游标绑定主体与对话：跨主体或跨对话复用一律 422 INVALID_CURSOR。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.session import Database
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.operations import AuditLog
from app.models.provenance import ConversationProvenance
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_AUTH
from tests.support.merchant_v2 import merchant_session_headers, seed_product
from tests.support.trade import SHOP, bound_customer, database_of

pytestmark = pytest.mark.integration

JSON_HEADERS = {"Accept": "application/json"}
SHOP_LIST = "/api/v2/shop/conversations"
MERCHANT_LIST = "/api/v2/merchant/conversations"


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


def _patch_llm(monkeypatch: pytest.MonkeyPatch, turns: list[LlmTurn]) -> None:
    """两端 Chat 共用同一串脚本回合：按调用顺序依次消费。"""

    fake = FakeLlmClient(turns=turns)
    for route in ("shop_chat", "merchant_chat"):
        monkeypatch.setattr(
            f"app.api.routes.v2.{route}.build_guarded_llm", lambda *args, **kwargs: fake
        )


async def _guest(client: AsyncClient) -> dict[str, str]:
    resp = await client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    assert resp.status_code == 201, resp.text
    return {"X-Session-Id": resp.json()["session_id"]}


async def _chat(
    client: AsyncClient,
    headers: dict[str, str],
    message: str,
    *,
    side: str = "shop",
    crid: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"client_request_id": crid or uuid4().hex, "message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    resp = await client.post(f"/api/v2/{side}/chat", json=body, headers={**headers, **JSON_HEADERS})
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _strip_request_id(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key != "request_id"}


async def _provenance_rows(database: Database, conversation_id: str) -> int:
    async with database.session() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ConversationProvenance)
            .where(ConversationProvenance.conversation_id == conversation_id)
        )
    return int(count or 0)


# ---- 列表：只含当前主体 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_cannot_list_other_customers_conversations(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("你好 A")])
    alice = await _guest(postgres_client)
    bob = await _guest(postgres_client)
    turn = await _chat(postgres_client, alice, "我是 A")

    mine = (await postgres_client.get(SHOP_LIST, headers=alice)).json()
    theirs = (await postgres_client.get(SHOP_LIST, headers=bob)).json()

    assert [item["id"] for item in mine["items"]] == [turn["conversation_id"]]
    assert mine["items"][0]["title"] == "我是 A"
    assert mine["has_more"] is False and mine["next_cursor"] is None
    assert theirs == {"items": [], "next_cursor": None, "has_more": False}


@pytest.mark.asyncio
async def test_bound_customer_sees_own_conversations_across_sessions(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已绑定顾客按 merchant_id + buyer_key 归属：换一个认证会话仍看得到自己的对话。"""

    _patch_llm(monkeypatch, [_answer("好的")])
    first = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-conv-1")
    turn = await _chat(postgres_client, first, "上次的围巾")
    second = await bound_customer(postgres_client, postgres_app, buyer_key="buyer-conv-1")

    items = (await postgres_client.get(SHOP_LIST, headers=second)).json()["items"]

    assert [item["id"] for item in items] == [turn["conversation_id"]]


@pytest.mark.asyncio
async def test_merchant_list_excludes_customer_and_other_merchant_conversations(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("顾客好"), _answer("商家好")])
    customer = await _guest(postgres_client)
    await _chat(postgres_client, customer, "在吗")
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    turn = await _chat(postgres_client, merchant, "今天库存怎样", side="merchant")
    other = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)

    mine = (await postgres_client.get(MERCHANT_LIST, headers=merchant)).json()["items"]
    theirs = (await postgres_client.get(MERCHANT_LIST, headers=other)).json()["items"]

    assert [item["id"] for item in mine] == [turn["conversation_id"]]
    assert theirs == []


@pytest.mark.asyncio
async def test_merchant_list_orders_by_last_activity(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.9.2：商家对话按 `updated_at DESC`——续写旧对话会把它顶到最前。"""

    _patch_llm(monkeypatch, [_answer("一"), _answer("二"), _answer("三")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    older = await _chat(postgres_client, merchant, "第一段", side="merchant")
    newer = await _chat(postgres_client, merchant, "第二段", side="merchant")
    before = (await postgres_client.get(MERCHANT_LIST, headers=merchant)).json()["items"]
    await _chat(
        postgres_client,
        merchant,
        "接着第一段",
        side="merchant",
        conversation_id=older["conversation_id"],
    )

    after = (await postgres_client.get(MERCHANT_LIST, headers=merchant)).json()["items"]

    assert [item["id"] for item in before] == [newer["conversation_id"], older["conversation_id"]]
    assert [item["id"] for item in after] == [older["conversation_id"], newer["conversation_id"]]


@pytest.mark.asyncio
async def test_list_pages_with_signed_cursor_bound_to_principal(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("一"), _answer("二")])
    alice = await _guest(postgres_client)
    bob = await _guest(postgres_client)
    older = await _chat(postgres_client, alice, "第一段")
    newer = await _chat(postgres_client, alice, "第二段")

    page1 = (await postgres_client.get(SHOP_LIST, params={"limit": 1}, headers=alice)).json()
    page2 = (
        await postgres_client.get(
            SHOP_LIST, params={"limit": 1, "cursor": page1["next_cursor"]}, headers=alice
        )
    ).json()
    stolen = await postgres_client.get(
        SHOP_LIST, params={"limit": 1, "cursor": page1["next_cursor"]}, headers=bob
    )

    assert [item["id"] for item in page1["items"]] == [newer["conversation_id"]]
    assert page1["has_more"] is True
    assert [item["id"] for item in page2["items"]] == [older["conversation_id"]]
    assert page2 == {**page2, "has_more": False, "next_cursor": None}
    assert stolen.status_code == 422
    assert stolen.json()["code"] == "INVALID_CURSOR"


# ---- 详情 --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_returns_messages_in_order_with_final_answer(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("你好，有什么可以帮你？"), _answer("围巾在第二页")])
    alice = await _guest(postgres_client)
    first = await _chat(postgres_client, alice, "在吗")
    second = await _chat(
        postgres_client, alice, "围巾在哪", conversation_id=first["conversation_id"]
    )

    resp = await postgres_client.get(f"{SHOP_LIST}/{first['conversation_id']}", headers=alice)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversation"]["id"] == first["conversation_id"]
    messages = body["messages"]["items"]
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "在吗"),
        ("assistant", "你好，有什么可以帮你？"),
        ("user", "围巾在哪"),
        ("assistant", "围巾在第二页"),
    ]
    assert messages[0]["answer"] is None
    assert messages[1]["answer"] == first
    assert messages[3]["answer"] == second


@pytest.mark.asyncio
async def test_merchant_history_restores_scoped_answer_feedback(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("第一条"), _answer("第二条")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    first = await _chat(postgres_client, merchant, "问题一", side="merchant")
    second = await _chat(
        postgres_client,
        merchant,
        "问题二",
        side="merchant",
        conversation_id=first["conversation_id"],
    )
    path = f"{MERCHANT_LIST}/{first['conversation_id']}"
    before = (await postgres_client.get(path, headers=merchant)).json()["messages"]["items"]
    assert before[0]["feedback"] is None
    assert before[1]["feedback"] == {"adopted": False, "reaction": None, "reason": None}
    assert before[3]["feedback"] == {"adopted": False, "reaction": None, "reason": None}

    for request in (
        {"kind": "ADOPTION", "adopted": True, "client_request_id": uuid4().hex},
        {
            "kind": "REACTION",
            "reaction": "DISLIKE",
            "reason": "不准确",
            "client_request_id": uuid4().hex,
        },
    ):
        response = await postgres_client.post(
            f"/api/v2/merchant/answers/{first['id']}/feedback",
            headers=merchant,
            json=request,
        )
        assert response.status_code == 200, response.text

    after = (await postgres_client.get(path, headers=merchant)).json()["messages"]["items"]
    assert after[1]["feedback"] == {"adopted": True, "reaction": "DISLIKE", "reason": "不准确"}
    assert after[3]["answer"]["id"] == second["id"]
    assert after[3]["feedback"] == {"adopted": False, "reaction": None, "reason": None}
    other = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)
    assert (await postgres_client.get(path, headers=other)).status_code == 403


@pytest.mark.asyncio
async def test_message_cursor_is_bound_to_its_conversation(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("一"), _answer("二")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    a = await _chat(postgres_client, merchant, "对话 A", side="merchant")
    b = await _chat(postgres_client, merchant, "对话 B", side="merchant")

    page1 = (
        await postgres_client.get(
            f"{MERCHANT_LIST}/{a['conversation_id']}", params={"limit": 1}, headers=merchant
        )
    ).json()["messages"]
    page2 = (
        await postgres_client.get(
            f"{MERCHANT_LIST}/{a['conversation_id']}",
            params={"limit": 1, "cursor": page1["next_cursor"]},
            headers=merchant,
        )
    ).json()["messages"]
    crossed = await postgres_client.get(
        f"{MERCHANT_LIST}/{b['conversation_id']}",
        params={"limit": 1, "cursor": page1["next_cursor"]},
        headers=merchant,
    )

    assert [m["role"] for m in page1["items"]] == ["user"]
    assert [m["role"] for m in page2["items"]] == ["assistant"]
    assert page2["has_more"] is False
    assert crossed.status_code == 422
    assert crossed.json()["code"] == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_foreign_conversation_detail_indistinguishable_from_missing(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("商家二的对话")])
    other = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)
    foreign_id = (await _chat(postgres_client, other, "别人的", side="merchant"))["conversation_id"]
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    missing = await postgres_client.get(f"{MERCHANT_LIST}/{uuid4()}", headers=merchant)
    foreign = await postgres_client.get(f"{MERCHANT_LIST}/{foreign_id}", headers=merchant)
    malformed = await postgres_client.get(f"{MERCHANT_LIST}/not-a-uuid", headers=merchant)

    assert missing.status_code == foreign.status_code == malformed.status_code == 403
    assert foreign.json()["code"] == "RESOURCE_FORBIDDEN"
    assert foreign.json()["details"] == []
    assert _strip_request_id(missing.json()) == _strip_request_id(foreign.json())
    assert _strip_request_id(malformed.json()) == _strip_request_id(foreign.json())
    async with database_of(postgres_app).session() as session:
        audited = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.event_type == "RESOURCE_SCOPE_VIOLATION",
                AuditLog.resource_type == "conversation",
            )
        )
    assert audited == 3


@pytest.mark.asyncio
async def test_merchant_cannot_open_customer_conversation_of_own_shop(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同店也不行：顾客对话只属于顾客，商家目录与详情都看不到（两端按登录主体隔离）。"""

    _patch_llm(monkeypatch, [_answer("顾客好")])
    customer = await _guest(postgres_client)
    cid = (await _chat(postgres_client, customer, "在吗"))["conversation_id"]
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.get(f"{MERCHANT_LIST}/{cid}", headers=merchant)

    assert resp.status_code == 403
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"


# ---- 删除 --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_hides_conversation_and_clears_provenance(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = database_of(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, title="羊毛围巾")
    _patch_llm(
        monkeypatch,
        [_call("search_products", "c1", query="围巾"), _answer("找到羊毛围巾"), _answer("新的")],
    )
    alice = await _guest(postgres_client)
    cid = (await _chat(postgres_client, alice, "有围巾吗"))["conversation_id"]
    assert await _provenance_rows(database, cid) > 0

    deleted = await postgres_client.delete(f"{SHOP_LIST}/{cid}", headers=alice)

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert await _provenance_rows(database, cid) == 0
    assert (await postgres_client.get(SHOP_LIST, headers=alice)).json()["items"] == []
    again = await postgres_client.delete(f"{SHOP_LIST}/{cid}", headers=alice)
    detail = await postgres_client.get(f"{SHOP_LIST}/{cid}", headers=alice)
    assert again.status_code == detail.status_code == 403
    assert again.json()["code"] == detail.json()["code"] == "RESOURCE_FORBIDDEN"
    # 删掉的对话不能再被续写，也不能静默新建。
    resumed = await postgres_client.post(
        "/api/v2/shop/chat",
        headers=alice,
        json={"message": "接着聊", "conversation_id": cid, "client_request_id": "deleted"},
    )
    assert resumed.status_code == 403
    assert resumed.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_customer_cannot_delete_another_customers_conversation(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("你好 A")])
    alice = await _guest(postgres_client)
    bob = await _guest(postgres_client)
    cid = (await _chat(postgres_client, alice, "我是 A"))["conversation_id"]

    resp = await postgres_client.delete(f"{SHOP_LIST}/{cid}", headers=bob)

    assert resp.status_code == 403
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"
    items = (await postgres_client.get(SHOP_LIST, headers=alice)).json()["items"]
    assert [item["id"] for item in items] == [cid]


@pytest.mark.asyncio
async def test_merchant_delete_is_scoped_to_merchant(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("好")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    cid = (await _chat(postgres_client, merchant, "看库存", side="merchant"))["conversation_id"]
    other = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)

    foreign = await postgres_client.delete(f"{MERCHANT_LIST}/{cid}", headers=other)
    own = await postgres_client.delete(f"{MERCHANT_LIST}/{cid}", headers=merchant)

    assert foreign.status_code == 403
    assert own.status_code == 204
    assert (await postgres_client.get(MERCHANT_LIST, headers=merchant)).json()["items"] == []


# ---- 角色 --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_route_rejects_merchant_session(postgres_client: AsyncClient) -> None:
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.get(SHOP_LIST, headers=merchant)

    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"


@pytest.mark.asyncio
async def test_merchant_route_rejects_customer_session(postgres_client: AsyncClient) -> None:
    customer = await _guest(postgres_client)

    resp = await postgres_client.delete(f"{MERCHANT_LIST}/{uuid4()}", headers=customer)

    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"


@pytest.mark.asyncio
async def test_directory_requires_session(postgres_client: AsyncClient) -> None:
    resp = await postgres_client.get(MERCHANT_LIST)

    assert resp.status_code == 401
    assert resp.json()["code"] == "SESSION_REQUIRED"
