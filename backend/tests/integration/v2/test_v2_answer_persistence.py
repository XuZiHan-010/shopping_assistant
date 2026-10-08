"""v2 Chat 回答落 `answers` 表（N2 模块 D，Task 2 缺口修复）——全程 Fake LLM。

两件事一起验：
- v2 商家回答能被反馈（此前回答 ID 不落库，对 v2 回答提交反馈一律 403）；顾客回答不能被商家反馈；
- v1 接口只看 v1 数据：v1 会话目录、v1 回答反馈、v1 幂等查找都不会碰到 v2 对话或 v2 回答——
  否则同店商家能经 v1 目录读到顾客对话（R5），v1 还会拿 v1 结构解析 v2 回答。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.answer import Answer
from app.repositories.chatbi import ChatBiRepository
from app.repositories.conversation import ConversationRepository
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers
from tests.support.trade import SHOP, database_of

pytestmark = pytest.mark.integration

JSON_HEADERS = {"Accept": "application/json"}


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, turns: list[LlmTurn]) -> None:
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
    client: AsyncClient, headers: dict[str, str], message: str, *, side: str, crid: str
) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v2/{side}/chat",
        json={"client_request_id": crid, "message": message},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def _feedback(
    client: AsyncClient, headers: dict[str, str], answer_id: str, body: dict[str, Any]
) -> Any:
    return await client.post(
        f"/api/v2/merchant/answers/{answer_id}/feedback",
        json={"client_request_id": uuid4().hex, **body},
        headers=headers,
    )


# ---- v2 回答可被反馈 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_merchant_can_give_feedback_on_a_v2_chat_answer(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("本周库存正常")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    turn = await _chat(postgres_client, merchant, "库存怎样", side="merchant", crid="m-1")

    adopted = await _feedback(
        postgres_client, merchant, turn["id"], {"kind": "ADOPTION", "adopted": True}
    )
    disliked = await _feedback(
        postgres_client,
        merchant,
        turn["id"],
        {"kind": "REACTION", "reaction": "DISLIKE", "reason": "数字不对"},
    )

    assert adopted.status_code == 200, adopted.text
    assert disliked.status_code == 200, disliked.text
    assert disliked.json()["adopted"] is True
    assert disliked.json()["reaction"] == "DISLIKE"


@pytest.mark.asyncio
async def test_v2_answer_row_matches_the_chat_response(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回答 ID、目录详情里的回答与反馈用的 answer_id 是同一个东西。"""

    _patch_llm(monkeypatch, [_answer("好的")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    turn = await _chat(postgres_client, merchant, "你好", side="merchant", crid="m-row")

    async with database_of(postgres_app).session() as session:
        row = await session.get(Answer, UUID(turn["id"]))

    assert row is not None
    assert row.surface == "MERCHANT"
    assert row.merchant_id == MERCHANT_ONE_ID
    assert str(row.conversation_id) == turn["conversation_id"]
    assert row.processing_status == "SUCCEEDED"
    assert row.response_payload == turn


@pytest.mark.asyncio
async def test_merchant_cannot_give_feedback_on_a_customer_answer(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("欢迎光临")])
    customer = await _guest(postgres_client)
    turn = await _chat(postgres_client, customer, "在吗", side="shop", crid="s-1")
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    foreign = await _feedback(
        postgres_client, merchant, turn["id"], {"kind": "ADOPTION", "adopted": True}
    )
    missing = await _feedback(
        postgres_client, merchant, str(uuid4()), {"kind": "ADOPTION", "adopted": True}
    )

    assert foreign.status_code == missing.status_code == 403
    assert foreign.json()["code"] == missing.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_customers_of_one_shop_can_reuse_a_client_request_id(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1 唯一索引 `(merchant_id, client_request_id)` 不约束 v2 行（契约 §8.7.3）。"""

    _patch_llm(monkeypatch, [_answer("你好 A"), _answer("你好 B")])
    alice = await _guest(postgres_client)
    bob = await _guest(postgres_client)

    first = await _chat(postgres_client, alice, "我是 A", side="shop", crid="same-crid")
    second = await _chat(postgres_client, bob, "我是 B", side="shop", crid="same-crid")

    assert first["id"] != second["id"]
    async with database_of(postgres_app).session() as session:
        rows = (
            await session.scalars(select(Answer).where(Answer.client_request_id == "same-crid"))
        ).all()
    assert {row.surface for row in rows} == {"SHOP"}
    assert len(rows) == 2


# ---- v1 只看 v1 ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_conversation_list_excludes_v2_and_customer_conversations(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_llm(monkeypatch, [_answer("顾客好"), _answer("商家好")])
    customer = await _guest(postgres_client)
    shop_turn = await _chat(postgres_client, customer, "我的私事", side="shop", crid="s-2")
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    merchant_turn = await _chat(postgres_client, merchant, "看库存", side="merchant", crid="m-2")

    listing = await postgres_client.get("/api/conversations", headers=MERCHANT_ONE_AUTH)
    detail = await postgres_client.get(
        f"/api/conversations/{shop_turn['conversation_id']}", headers=MERCHANT_ONE_AUTH
    )

    assert listing.status_code == 200, listing.text
    listed = {item["id"] for item in listing.json()["items"]}
    assert shop_turn["conversation_id"] not in listed
    assert merchant_turn["conversation_id"] not in listed
    assert detail.status_code == 403
    assert detail.json()["code"] == "MERCHANT_SCOPE_VIOLATION"


@pytest.mark.asyncio
async def test_v1_feedback_cannot_touch_a_v2_answer(
    postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1 反馈一次覆盖采纳与赞踩两列，碰到 v2 回答会破坏「互不覆盖」语义。"""

    _patch_llm(monkeypatch, [_answer("好")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    turn = await _chat(postgres_client, merchant, "你好", side="merchant", crid="m-3")

    resp = await postgres_client.post(
        f"/api/answers/{turn['id']}/feedback",
        json={"is_adopted": True, "reaction": None},
        headers=MERCHANT_ONE_AUTH,
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_v1_idempotency_lookup_ignores_v2_answers(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v1 用同一个 `client_request_id` 重试，不能把 v2 回答当成自己的第一次结果重放。"""

    _patch_llm(monkeypatch, [_answer("好")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    await _chat(postgres_client, merchant, "你好", side="merchant", crid="shared-crid")

    async with database_of(postgres_app).session() as session:
        found = await ConversationRepository(session).get_answer_by_client_request(
            MERCHANT_ONE_ID, "shared-crid"
        )

    assert found is None


@pytest.mark.asyncio
async def test_chatbi_rollup_counts_only_v1_answers(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chat BI 按 v1 结构解析回答；v2 回答接入前需先定口径，现阶段不计入。"""

    _patch_llm(monkeypatch, [_answer("好")])
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    await _chat(postgres_client, merchant, "你好", side="merchant", crid="m-bi")
    today = datetime.now(UTC).date()
    window = (today - timedelta(days=1), today + timedelta(days=1))  # 业务时区可能跨日

    async with database_of(postgres_app).session() as session:
        rows = (
            await session.execute(
                ChatBiRepository(database_of(postgres_app))._source_select(*window)
            )
        ).all()

    assert rows == []
