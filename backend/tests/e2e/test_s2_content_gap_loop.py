"""场景 S2：内容缺口闭环（PRD M4、D11③④，商家计划 Task 3、Task 7）——后端 E2E，全程 Fake LLM。

```text
顾客问未填写的产地 → 顾客端 Agent 说明缺失 → 内容缺口信号 +1
→ 商家在信号列表里看到该信号 → 商家 Agent 起草补充 → 审批应用
→ 顾客端再问同一问题能回答，该信号不再计数
```

按 2026-09-26 用户裁定："商家能看到该信号"用信号列表 API
（`GET /api/v2/merchant/customer-signals`）验证，而不是依赖简报生成时机；
本场景核对同一份底层事实（信号已计数、商家侧可查、审批后不再计数）。

第 1、5 步都经**顾客端工具**读取（`get_product_attribute`），不直接查库：证明两端共享
同一份商品内容事实，不是各自维护状态。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.analytics import Product
from app.models.drafts import Draft
from app.repositories.audit import AuditRepository
from app.services.v2.drafts import DatabaseDraftSink
from app.tools.customer import build_customer_tools
from app.tools.gates import AuditRepositorySecurityAudit, DatabaseProvenanceStore, ToolGates
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers

pytestmark = pytest.mark.integration

JSON_HEADERS = {"Accept": "application/json"}
CHAT_PATH = "/api/v2/merchant/chat"
DRAFTS_PATH = "/api/v2/merchant/drafts"
SIGNALS_PATH = "/api/v2/merchant/customer-signals"
PRINCIPAL_SECRET = b"s2-content-gap-tests-principal-secret-01"
CONVERSATION = "conv-s2-customer-1"


def _call(call_id: str, tool: str, **arguments: Any) -> LlmTurn:
    return LlmTurn(
        text="",
        tool_calls=[
            LlmToolCall(
                call_id=call_id, tool_name=tool,
                arguments_json=json.dumps(arguments, ensure_ascii=False),
            )
        ],
        stop_reason="TOOL_USE",
        tokens=10,
    )


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _seed_product(database: Database, merchant_id: UUID) -> UUID:
    """已登记必填属性清单的类目（"女装"要求产地/材质/尺码），且不预填产地——制造缺口。"""

    product_id = uuid4()
    async with database.session() as session:
        session.add(Product(
            id=product_id, merchant_id=merchant_id, business_date=datetime.now(UTC).date(),
            product_code=f"s2-{product_id.hex[:12]}", title="S2 测试连衣裙", category="女装",
            price=Decimal("199.00"), status="ONLINE", listed_at=datetime.now(UTC),
            stock_on_hand=10, stock_reserved=0,
            attributes={
                "材质": {"value": "棉", "source": "DEMO"},
                "尺码": {"value": "M", "source": "DEMO"},
            },
        ))
        await session.commit()
    return product_id


def _customer_gates(database: Database) -> ToolGates:
    registry = ToolRegistry()
    for spec in build_customer_tools(database):
        registry.register(spec)
    return ToolGates(
        registry,
        provenance=DatabaseProvenanceStore(database),
        principal_secret=PRINCIPAL_SECRET,
        audit=AuditRepositorySecurityAudit(AuditRepository(database)),
        drafts=DatabaseDraftSink(database),
    )


def _customer_ctx(merchant_id: UUID, buyer_key: str) -> ToolContext:
    session = SessionContext(
        session_record_id=uuid4(), role=SessionRole.CUSTOMER,
        merchant_id=merchant_id, buyer_key=buyer_key, shop_slug=None,
    )
    return ToolContext(session=session, conversation_id=CONVERSATION, request_id="req-s2-1")


async def _ask_about_origin(gates: ToolGates, ctx: ToolContext, product_id: UUID) -> str | None:
    result = await gates.invoke(
        ctx, "get_product_attribute", {"product_id": str(product_id), "attribute": "产地"}
    )
    assert result.ok
    payload = result.payload
    assert isinstance(payload, dict)
    return payload["value"]  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_s2_content_gap_to_draft_to_answerable(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    product_id = await _seed_product(database, MERCHANT_ONE_ID)
    customer_gates = _customer_gates(database)
    customer_ctx = _customer_ctx(MERCHANT_ONE_ID, "s2-buyer")

    # 1. 顾客问未填写的产地——顾客端 Agent（工具直接）如实说明缺失，不替商家编造。
    value = await _ask_about_origin(customer_gates, customer_ctx, product_id)
    assert value is None

    # 2. 内容缺口信号 +1（同一事务内由 READ_ONLY 工具触发的派生计数）。
    merchant_headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    signals = (
        await postgres_client.get(SIGNALS_PATH, headers=merchant_headers)
    ).json()["items"]
    gap_signals = [s for s in signals if s["kind"] == "CONTENT_GAP"]
    assert len(gap_signals) == 1
    assert gap_signals[0]["product_id"] == str(product_id)
    assert gap_signals[0]["count"] == 1

    # 3. 商家在信号列表里看到该信号后，让 Agent 读取商品记录并起草补充。
    fake = FakeLlmClient(
        turns=[
            _call("c1", "get_product_content", product_id=str(product_id)),
            _call(
                "c2", "draft_content_change", product_id=str(product_id),
                attributes={
                    "产地": {"value": "浙江", "source_type": "MERCHANT_STATED"}
                },
            ),
            _answer("已为「产地」起草补充，请到审批界面确认。"),
        ]
    )
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    chat = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "s2-chat", "message": "信号里说有人问产地，帮我补上"},
        headers={**merchant_headers, **JSON_HEADERS},
    )
    assert chat.status_code == 200, chat.text
    assert [c["tool_name"] for c in chat.json()["tool_calls"]] == [
        "get_product_content", "draft_content_change",
    ]
    async with database.session() as session:
        draft = (
            (await session.execute(select(Draft).where(Draft.merchant_id == MERCHANT_ONE_ID)))
            .scalars()
            .one()
        )
    assert draft.state == "STAGED"

    # 4. 商家在审批界面批准（证据只从 GET /drafts/{id} 签发）。
    detail = await postgres_client.get(f"{DRAFTS_PATH}/{draft.id}", headers=merchant_headers)
    evidence = detail.json()["approval_evidence"]
    assert evidence
    applied = await postgres_client.post(
        f"{DRAFTS_PATH}/{draft.id}/apply",
        json={
            "client_request_id": "s2-apply", "draft_version": draft.draft_version,
            "target_version": 1, "approval_evidence": evidence,
        },
        headers=merchant_headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["draft"]["state"] == "APPLIED"

    # 5. 顾客端再问同一问题能回答——经顾客工具读取，证明两端共享同一份商品内容事实。
    value_after = await _ask_about_origin(customer_gates, customer_ctx, product_id)
    assert value_after == "浙江"

    # 6. 该信号不再计数：应用后 content_version 已变化，同一版本下重复提问不再新增计数。
    signals_after = (
        await postgres_client.get(SIGNALS_PATH, headers=merchant_headers)
    ).json()["items"]
    gap_after = [s for s in signals_after if s["kind"] == "CONTENT_GAP"]
    assert len(gap_after) == 1
    assert gap_after[0]["count"] == 1  # 应用前的那一次，应用后属性已补不再新增
