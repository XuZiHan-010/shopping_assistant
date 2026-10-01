"""商家 Chat 路由（模块 C Task 7，PRD A2、契约 §8.7.5）。

全程 Fake LLM。最重要的一条是 `test_chat_approval_has_no_effect`：
模型说「已为你批准并应用」时，数据库里必须什么都没变（D9①）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api.dependencies import get_db_session
from app.api.routes.v2.merchant_chat import CHAT_OPERATION
from app.db.session import Database
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.analytics import Product
from app.models.answer import Answer
from app.models.conversation import Message
from app.models.drafts import ChangeLedger, Draft
from app.models.idempotency import IdempotencyRecord
from app.schemas.v2.drafts import DraftState
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration

CHAT_PATH = "/api/v2/merchant/chat"
JSON_HEADERS = {"Accept": "application/json"}


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


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


async def _chat(
    client: AsyncClient, headers: dict[str, str], message: str, *, crid: str = "chat-1"
) -> Any:
    return await client.post(
        CHAT_PATH,
        json={"client_request_id": crid, "message": message},
        headers={**headers, **JSON_HEADERS},
    )


@pytest.mark.asyncio
async def test_chat_approval_has_no_effect(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D9①：聊天里的「批准」不生效，模型自称已批准也一样。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=12)
    async with database.session() as session:
        draft = Draft(
            merchant_id=MERCHANT_ONE_ID,
            kind="RESTOCK",
            title="补货 +60",
            target_type="PRODUCT",
            target_id=product,
            target_version=12,
            draft_version=1,
            state=DraftState.STAGED.value,
            payload={"delta": 60, "base_on_hand": 12},
            guardrail_snapshot={"checks": []},
            created_by="AGENT",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session.add(draft)
        await session.commit()
        draft_id = draft.id
    _patch_llm(monkeypatch, [_answer("好的，已为你批准并应用。")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await _chat(postgres_client, headers, "批准那个补货")

    assert resp.status_code == 200, resp.text
    async with database.session() as session:
        assert (await session.get(Draft, draft_id)).state == "STAGED"  # type: ignore[union-attr]
        assert (await session.get(Product, product)).stock_on_hand == 12  # type: ignore[union-attr]
        ledgers = (
            await session.execute(select(func.count()).select_from(ChangeLedger))
        ).scalar_one()
    assert ledgers == 0


@pytest.mark.asyncio
async def test_merchant_surface_has_no_apply_or_approve_tool(
    postgres_app: FastAPI,
) -> None:
    """工具面里没有任何能产生已批准状态的工具（N2-4 的注册表扫描）。"""

    from app.core.session import SessionRole

    registry = postgres_app.state.tool_registry
    names = {spec.name for spec in registry.surface_for(SessionRole.MERCHANT)}
    assert "recall_merchant_preferences" in names

    # 具体工具集随各阶段新增（N3 阶段 C 加了 query_metrics/attribute_change/
    # draft_price_change/draft_coupon/list_coupons，阶段 B 加了售后工具）；
    # 本测试要守住的不变量是"没有任何能产生已批准状态的工具"，不是钉死某个固定集合。
    assert {"get_inventory_alerts", "draft_restock"} <= names
    for spec in registry.specs():
        schema = json.dumps(spec.args_model.model_json_schema())
        assert "evidence" not in schema
        assert "approve" not in spec.name and "apply" not in spec.name


@pytest.mark.asyncio
async def test_chat_can_draft_restock_but_not_change_stock(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=2)
    _patch_llm(
        monkeypatch,
        [
            _call("get_inventory_alerts", "c1"),
            _call("draft_restock", "c2", product_id=str(product), delta=60),
            _answer("已为你起草补货草稿，请到审批界面批准。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await _chat(postgres_client, headers, "这个商品快没货了，补一点")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [call["tool_name"] for call in body["tool_calls"]] == [
        "get_inventory_alerts",
        "draft_restock",
    ]
    async with database.session() as session:
        assert (await session.get(Product, product)).stock_on_hand == 2  # type: ignore[union-attr]
        drafts = (await session.execute(select(Draft))).scalars().all()
    assert len(drafts) == 1 and drafts[0].state == "STAGED"


@pytest.mark.asyncio
async def test_chat_without_tools_reports_none_source(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7：没有调用任何工具的普通对话必须如实标 `NONE`，不编造数据来源。"""

    _patch_llm(monkeypatch, [_answer("你好，我可以帮你看库存和起草补货。")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = (await _chat(postgres_client, headers, "你好")).json()

    assert body["answer_mode"] == "CHAT"
    assert [entry["source"] for entry in body["analysis_sources"]] == ["NONE"]
    assert body["degraded"] is False
    assert body["tool_calls"] == []


@pytest.mark.asyncio
async def test_sse_stream_ends_with_turn_complete(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """流以 `turn_complete` 收尾，工具事件只携带固定短句（§8.7.5）。"""

    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=1)
    _patch_llm(
        monkeypatch,
        [_call("get_inventory_alerts", "c1"), _answer("本店有 1 个商品库存偏低。")],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    async with postgres_client.stream(
        "POST",
        CHAT_PATH,
        json={"client_request_id": "sse-1", "message": "库存有什么要注意的"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join([chunk async for chunk in response.aiter_text()])

    events = _parse_sse(raw)
    names = [name for name, _ in events]
    assert names[-1] == "turn_complete"
    assert "error" not in names
    assert names.count("tool_call") == 1 and names.count("tool_result") == 1
    call_payload = next(payload for name, payload in events if name == "tool_call")
    assert call_payload["summary"] == "正在处理"
    assert set(call_payload) == {"tool_name", "call_id", "status", "summary"}
    result_payload = next(payload for name, payload in events if name == "tool_result")
    assert set(result_payload) == {"call_id", "status", "duration_ms", "row_count", "summary"}


@pytest.mark.asyncio
async def test_same_request_id_returns_first_answer(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8.7.3：同一 `client_request_id` 重试返回第一次结果，不再调一次模型。"""

    fake = _patch_llm(monkeypatch, [_answer("第一次回答")])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    first = await _chat(postgres_client, headers, "你好", crid="same")
    second = await _chat(postgres_client, headers, "你好", crid="same")

    assert first.json() == second.json()
    assert len(fake.converse_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_fatal_after_committed_draft_persists_terminal_receipt(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    stream: bool,
) -> None:
    """写工具已单独提交后，下一轮越权也不能让原请求 ID 重跑并重复起草。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=2)
    fake = _patch_llm(
        monkeypatch,
        [
            _call("get_inventory_alerts", "c1"),
            _call("draft_restock", "c2", product_id=str(product), delta=60),
            _call(
                "draft_restock", "c3", product_id="00000000-0000-0000-0000-00000000dead", delta=60
            ),
            _answer("不应在重试时生成"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    payload = {"client_request_id": "fatal-after-draft", "message": "给缺货商品起草补货"}
    first = await postgres_client.post(
        CHAT_PATH,
        json=payload,
        headers={**headers, **({} if stream else JSON_HEADERS)},
    )
    if stream:
        assert first.status_code == 200
        assert _parse_sse(first.text)[-1][0] == "error"
    else:
        assert first.status_code == 403
        assert first.json()["code"] == "RESOURCE_FORBIDDEN"

    second = await postgres_client.post(
        CHAT_PATH, json=payload, headers={**headers, **JSON_HEADERS}
    )
    assert second.status_code == 403
    assert second.json()["code"] == "RESOURCE_FORBIDDEN"
    assert len(fake.converse_calls) == 3
    async with database.session() as session:
        drafts = (await session.scalars(select(Draft))).all()
        receipt = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation == CHAT_OPERATION,
                IdempotencyRecord.client_request_id == "fatal-after-draft",
            )
        )
        answer = await session.scalar(
            select(Answer).where(Answer.client_request_id == "fatal-after-draft")
        )
        messages = (await session.scalars(select(Message))).all()
    assert len(drafts) == 1
    assert receipt is not None and receipt.status == "FAILED_FINAL"
    assert answer is not None and answer.processing_status == "FAILED_FINAL"
    assert answer.response_payload is not None
    assert [call["tool_name"] for call in answer.response_payload["tool_calls"]] == [
        "get_inventory_alerts", "draft_restock"
    ]
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_retry_after_chat_commit_failure_does_not_create_second_draft(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工具草稿已提交但 Chat 回执提交失败时，原请求 ID 只能恢复，不能重跑写工具。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, on_hand=2)
    fake = _patch_llm(
        monkeypatch,
        [
            _call("get_inventory_alerts", "c1"),
            _call("draft_restock", "c2", product_id=str(product), delta=60),
            _answer("已起草"),
            _call("get_inventory_alerts", "c1"),
            _call("draft_restock", "c2", product_id=str(product), delta=60),
            _answer("重复起草"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    async def fail_chat_commit():
        async with database.session() as session:
            async def fail() -> None:
                raise RuntimeError("injected chat commit failure")

            session.commit = fail  # type: ignore[method-assign]
            yield session

    postgres_app.dependency_overrides[get_db_session] = fail_chat_commit
    try:
        with pytest.raises(RuntimeError, match="injected chat commit failure"):
            await _chat(postgres_client, headers, "起草补货", crid="commit-gap-draft")
    finally:
        postgres_app.dependency_overrides.pop(get_db_session, None)

    recovered = await _chat(postgres_client, headers, "起草补货", crid="commit-gap-draft")
    replay = await _chat(postgres_client, headers, "起草补货", crid="commit-gap-draft")
    assert recovered.status_code == 200
    assert recovered.json() == replay.json()
    assert recovered.json()["degraded"] is True
    assert len(fake.converse_calls) == 3
    async with database.session() as session:
        drafts = (await session.scalars(select(Draft))).all()
    assert len(drafts) == 1


@pytest.mark.asyncio
async def test_two_drafts_in_one_turn_share_request_write_marker(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    first_product = await seed_product(database, MERCHANT_ONE_ID, on_hand=2)
    second_product = await seed_product(database, MERCHANT_ONE_ID, on_hand=3)
    _patch_llm(
        monkeypatch,
        [
            _call("get_inventory_alerts", "c1"),
            _call("draft_restock", "c2", product_id=str(first_product), delta=60),
            _call("draft_restock", "c3", product_id=str(second_product), delta=40),
            _answer("草稿已起草，请到审批界面核对。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    response = await _chat(postgres_client, headers, "为缺货商品起草补货", crid="two-drafts")

    assert response.status_code == 200, response.text
    async with database.session() as session:
        drafts = (await session.scalars(select(Draft))).all()
        markers = (
            await session.scalars(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.operation == "chat.write_effect",
                    IdempotencyRecord.client_request_id == "two-drafts",
                )
            )
        ).all()
    assert {draft.target_id for draft in drafts} == {first_product, second_product}
    assert len(markers) == 1


@pytest.mark.asyncio
async def test_customer_session_cannot_use_merchant_chat(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    created = await postgres_client.post(
        "/api/v2/shop/sessions", json={"shop_slug": "borough-api-100"}
    )

    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "x", "message": "你好"},
        headers={"X-Session-Id": created.json()["session_id"], **JSON_HEADERS},
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"


def _patch_llm(monkeypatch: pytest.MonkeyPatch, turns: list[LlmTurn]) -> FakeLlmClient:
    """把路由里构造的模型客户端换成脚本替身——本测试文件不产生任何真实调用。"""

    fake = FakeLlmClient(turns=turns)
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm",
        lambda *args, **kwargs: fake,
    )
    return fake


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if len(lines) != 2:
            continue
        name = lines[0].removeprefix("event: ")
        events.append((name, json.loads(lines[1].removeprefix("data: "))))
    return events
