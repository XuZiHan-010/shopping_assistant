"""真实 ASGI 断开、交易工具及 PostgreSQL 回放链路，全程脚本模型。"""

import asyncio
import json
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models.cart import CartLine
from app.tools.gates import ToolGates
from tests.conftest import MERCHANT_ONE_ID
from tests.integration.v2.test_shop_chat import _call, _chat, _guest, _patch_llm
from tests.support.merchant_v2 import seed_product
from tests.support.trade import database_of

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_disconnect_persists_completed_write_and_retry_does_not_repeat(
    postgres_app, postgres_client, monkeypatch
):
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, title="围巾", on_hand=12)
    headers = await _guest(postgres_client)
    first_write = _call("set_cart_item", "cart-first", product_id=str(pid), quantity=1)
    second_write = _call("set_cart_item", "cart-second", product_id=str(pid), quantity=2)
    from dataclasses import replace

    writes = replace(first_write, tool_calls=first_write.tool_calls + second_write.tool_calls)
    fake = _patch_llm(monkeypatch, [_call("search_products", "search", query="围巾"), writes])
    started, release, disconnected = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = ToolGates.execute

    async def execute(self, ctx, call):
        result = await original(self, ctx, call)
        if result.display.call_id == "cart-first":
            started.set()
            await release.wait()
        return result

    monkeypatch.setattr(ToolGates, "execute", execute)
    payload = {"message": "加一件围巾", "client_request_id": "disconnect-retry"}
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {
                "type": "http.request",
                "body": json.dumps(payload).encode(),
                "more_body": False,
            }
        await started.wait()
        disconnected.set()
        return {"type": "http.disconnect"}

    async def send(message):
        pass

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v2/shop/chat",
        "raw_path": b"/api/v2/shop/chat",
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-session-id", headers["X-Session-Id"].encode()),
        ],
    }
    response = asyncio.create_task(postgres_app(scope, receive, send))
    try:
        await asyncio.wait_for(disconnected.wait(), 10)
        # 等传输层将断开通知到回合；写工具仍由屏障控制，不能被取消。
        await asyncio.sleep(0.05)
        assert not response.done()
    finally:
        release.set()
        await asyncio.wait_for(response, 10)
    replay = await _chat(
        postgres_client, headers, payload["message"], crid=payload["client_request_id"]
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["degraded"] is True
    assert [call["call_id"] for call in body["tool_calls"]] == ["search", "cart-first"]
    assert len(fake.converse_calls) == 2
    async with database.session() as session:
        line = (
            await session.scalars(select(CartLine).where(CartLine.product_id == UUID(str(pid))))
        ).one()
        assert line.quantity == 1
