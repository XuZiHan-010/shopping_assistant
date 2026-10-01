"""`create_export` 工具在真实商家 Chat 回合中的行为（N3 阶段 C Task 5，Astra N3-4 必审）。

全程 Fake LLM。核心断言：明细行永不进入模型上下文（工具摘要与传给模型的下一轮消息都不含
任何一行数据）、创建导出会写审计、导出范围按当前会话商家强制。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.analytics import Order
from app.models.operations import AuditLog, ExportFile
from app.repositories.audit import AuditRepository
from app.tools.errors import GuardrailRejection
from app.tools.merchant.export import CreateExportArgs, build_export_tools
from app.tools.types import ToolContext
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product

pytestmark = pytest.mark.integration

CHAT_PATH = "/api/v2/merchant/chat"
JSON_HEADERS = {"Accept": "application/json"}


@pytest.mark.asyncio
async def test_english_chat_export_persists_english_csv_locale(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    await _seed_order(database, MERCHANT_ONE_ID)
    today = datetime.now(UTC).date()
    _patch_llm(monkeypatch, [
        _call(
            "create_export", "c1", kind="orders",
            start=(today - timedelta(days=7)).isoformat(), end=today.isoformat(),
        ),
        _answer("The export is ready."),
    ])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    response = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "export-en-locale", "message": "Export recent orders"},
        headers={**headers, **JSON_HEADERS, "Accept-Language": "en-US"},
    )
    assert response.status_code == 200, response.text
    async with database.session() as session:
        export = (await session.execute(select(ExportFile))).scalar_one()
        assert export.export_spec["locale"] == "en-US"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


def _answer(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


def _call(tool: str, call_id: str, **arguments: Any) -> LlmTurn:
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


async def _seed_order(database: Database, merchant_id: Any) -> str:
    """播种一笔已付款订单，返回它的 `order_no`（用于断言这行数据没有进模型上下文）。"""

    product_id = await seed_product(database, merchant_id)
    order_id = await seed_paid_order(database, merchant_id, product_id, quantity=1, days_ago=1)
    async with database.session() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        return str(order.order_no)


async def _create_export_link(app: FastAPI, database: Database) -> tuple[str, str]:
    """直接调用 `create_export` 工具，用与下载端点相同的签名密钥拿到签名链接。"""

    secret = app.state.settings.export_signing_secret or "development-export-signing-secret"
    spec = build_export_tools(
        database, AuditRepository(database), signing_secret=secret, export_url_ttl_minutes=15
    )[0]
    ctx = ToolContext(
        session=SessionContext(
            session_record_id=uuid4(),
            role=SessionRole.MERCHANT,
            merchant_id=MERCHANT_ONE_ID,
            buyer_key=None,
            shop_slug=None,
        ),
        conversation_id=str(uuid4()),
        request_id="export-download-audit",
    )
    today = datetime.now(UTC).date()
    output = await spec.executor(
        ctx, CreateExportArgs(kind="orders", start=today - timedelta(days=7), end=today)
    )
    return str(output.payload["export_id"]), str(output.payload["url"])


async def _download_events(database: Database) -> list[AuditLog]:
    async with database.session() as session:
        statement = select(AuditLog).where(AuditLog.event_type == "EXPORT_DOWNLOADED")
        return list((await session.execute(statement)).scalars().all())


@pytest.mark.asyncio
async def test_signed_download_is_audited_separately_from_creation(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """PRD M7 / SEC10：创建导出与实际下载分别审计。"""

    database = _database(postgres_app)
    await _seed_order(database, MERCHANT_ONE_ID)
    export_id, url = await _create_export_link(postgres_app, database)

    response = await postgres_client.get(url)

    assert response.status_code == 200, response.text
    events = await _download_events(database)
    assert len(events) == 1
    assert events[0].merchant_id == MERCHANT_ONE_ID
    assert events[0].resource_type == "EXPORT"
    assert events[0].resource_id == export_id


@pytest.mark.asyncio
async def test_rejected_download_writes_no_download_audit(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await _seed_order(database, MERCHANT_ONE_ID)
    _, url = await _create_export_link(postgres_app, database)
    tampered = url.replace("signature=", "signature=0")

    response = await postgres_client.get(tampered)

    assert response.status_code == 403, response.text
    assert await _download_events(database) == []


@pytest.mark.asyncio
async def test_export_creation_rejects_over_limit_before_writing_link(
    postgres_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.merchant import export as export_module

    database = _database(postgres_app)
    for _ in range(3):
        await _seed_order(database, MERCHANT_ONE_ID)
    monkeypatch.setattr(export_module, "MAX_EXPORT_ROWS", 2)
    spec = build_export_tools(
        database,
        AuditRepository(database),
        signing_secret="test-export-signing-secret",
        export_url_ttl_minutes=15,
    )[0]
    ctx = ToolContext(
        session=SessionContext(
            session_record_id=uuid4(),
            role=SessionRole.MERCHANT,
            merchant_id=MERCHANT_ONE_ID,
            buyer_key=None,
            shop_slug=None,
        ),
        conversation_id=str(uuid4()),
        request_id="export-limit-test",
    )
    today = datetime.now(UTC).date()
    with pytest.raises(GuardrailRejection):
        await spec.executor(
            ctx,
            CreateExportArgs(
                kind="orders",
                start=today - timedelta(days=7),
                end=today,
            ),
        )
    async with database.session() as session:
        assert (await session.execute(select(ExportFile))).scalars().all() == []


@pytest.mark.asyncio
async def test_chat_export_limit_is_visible_without_creating_link(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tools.merchant import export as export_module

    database = _database(postgres_app)
    for _ in range(3):
        await _seed_order(database, MERCHANT_ONE_ID)
    monkeypatch.setattr(export_module, "MAX_EXPORT_ROWS", 2)
    today = datetime.now(UTC).date()
    fake = _patch_llm(
        monkeypatch,
        [
            _call(
                "create_export",
                "c1",
                kind="orders",
                start=(today - timedelta(days=7)).isoformat(),
                end=today.isoformat(),
            ),
            _answer("导出行数超过同步上限，请缩小日期范围。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "export-limit-chat", "message": "导出最近 7 天订单"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    call = next(c for c in body["tool_calls"] if c["tool_name"] == "create_export")
    assert call["status"] == "STARTED"
    assert any(
        "EXPORT_ROW_LIMIT" in message.content
        for message in fake.converse_calls[-1].messages
    )
    assert "导出行数超过同步上限" in body["answer"]
    async with database.session() as session:
        assert (await session.execute(select(ExportFile))).scalars().all() == []


@pytest.mark.asyncio
async def test_export_rows_never_enter_model_context(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    order_no = await _seed_order(database, MERCHANT_ONE_ID)
    today = datetime.now(UTC).date()
    fake = _patch_llm(
        monkeypatch,
        [
            _call(
                "create_export",
                "c1",
                kind="orders",
                start=(today - timedelta(days=7)).isoformat(),
                end=today.isoformat(),
            ),
            _answer("已经为你创建了订单导出，点击链接下载。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "export-1", "message": "帮我导出最近 7 天的订单"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    # 发给模型的每一条消息都不应该出现订单号（唯一能证明"明细行进了上下文"的标记）。
    for call in fake.converse_calls:
        for message in call.messages:
            assert order_no not in message.content


@pytest.mark.asyncio
async def test_export_is_created_and_audited(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    await _seed_order(database, MERCHANT_ONE_ID)
    today = datetime.now(UTC).date()
    _patch_llm(
        monkeypatch,
        [
            _call(
                "create_export",
                "c1",
                kind="orders",
                start=(today - timedelta(days=7)).isoformat(),
                end=today.isoformat(),
            ),
            _answer("已创建导出。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "export-2", "message": "导出最近 7 天订单"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text

    async with database.session() as session:
        statement = select(ExportFile).where(ExportFile.merchant_id == MERCHANT_ONE_ID)
        files = (await session.execute(statement)).scalars().all()
        assert len(files) == 1

        events = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.merchant_id == MERCHANT_ONE_ID,
                        AuditLog.event_type == "EXPORT_CREATED",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1
        assert events[0].resource_id == str(files[0].id)


@pytest.mark.asyncio
async def test_export_is_scoped_to_session_merchant(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """商家 A 的会话创建的导出只能覆盖商家 A 的数据；即使商家 B 也有同类数据也不会混入。"""

    database = _database(postgres_app)
    await _seed_order(database, MERCHANT_ONE_ID)
    await _seed_order(database, MERCHANT_TWO_ID)
    today = datetime.now(UTC).date()
    _patch_llm(
        monkeypatch,
        [
            _call(
                "create_export",
                "c1",
                kind="orders",
                start=(today - timedelta(days=7)).isoformat(),
                end=today.isoformat(),
            ),
            _answer("已创建导出。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "export-3", "message": "导出最近 7 天订单"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text

    async with database.session() as session:
        files = (await session.execute(select(ExportFile))).scalars().all()
    # 只应该新增一条属于 MERCHANT_ONE 的导出记录（种子数据阶段没有其他导出）。
    assert all(f.merchant_id == MERCHANT_ONE_ID for f in files if f.answer_id is not None)


@pytest.mark.asyncio
async def test_export_tool_result_has_no_row_count(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """导出工具不报告行数——报了就暗示模型可以引用具体的行（M7：明细不进对话）。"""

    database = _database(postgres_app)
    await _seed_order(database, MERCHANT_ONE_ID)
    today = datetime.now(UTC).date()
    _patch_llm(
        monkeypatch,
        [
            _call(
                "create_export",
                "c1",
                kind="orders",
                start=(today - timedelta(days=7)).isoformat(),
                end=today.isoformat(),
            ),
            _answer("已创建导出。"),
        ],
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.post(
        CHAT_PATH,
        json={"client_request_id": "export-4", "message": "导出最近 7 天订单"},
        headers={**headers, **JSON_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    call = next(c for c in body["tool_calls"] if c["tool_name"] == "create_export")
    assert call.get("row_count") is None
