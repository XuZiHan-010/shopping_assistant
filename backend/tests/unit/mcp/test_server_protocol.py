"""MCP 入口的鉴权顺序与协议头（N5 A Task 2；契约 §8.14.3）。

处理顺序固定：鉴权 → 协议头与正文一致性 → 分发。鉴权失败时**连正文解析器都不碰**——
解析器本身也是攻击面。这里用假的凭证校验器与工具桥，只测协议层；凭证与工具的真实行为
见 `tests/integration/mcp/`。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from mcp_types.jsonrpc import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    UNSUPPORTED_PROTOCOL_VERSION,
)

from app.mcp import server as mcp_server
from app.mcp.credentials import McpPrincipal
from app.mcp.server import McpEndpoint, McpToolDescriptor, McpToolError

TOKEN = "valid-token"
PRINCIPAL = McpPrincipal(
    credential_id=UUID(int=7),
    merchant_id=UUID(int=100),
    scopes=frozenset({"query_metrics"}),
)
VERSION = "2026-07-28"


class FakeVerifier:
    def __init__(self) -> None:
        self.calls = 0

    async def verify(self, token: str) -> McpPrincipal | None:
        self.calls += 1
        return PRINCIPAL if token == TOKEN else None


class FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def list_tools(self, principal: McpPrincipal) -> list[McpToolDescriptor]:
        return [
            McpToolDescriptor(
                name="query_metrics",
                description="查询指标",
                input_schema={"type": "object", "properties": {"metric": {"type": "string"}}},
            )
        ]

    async def call_tool(
        self, principal: McpPrincipal, name: str, arguments: Mapping[str, Any], *, request_id: str
    ) -> Any:
        self.calls.append((name, arguments))
        if arguments.get("metric") == "not_a_metric":
            raise McpToolError(INVALID_PARAMS, "工具参数不合法")
        return {"metric": arguments.get("metric"), "value": "42.00"}


@pytest.fixture
def verifier() -> FakeVerifier:
    return FakeVerifier()


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
async def client(verifier: FakeVerifier, bridge: FakeBridge) -> AsyncIterator[AsyncClient]:
    endpoint = McpEndpoint(verifier=verifier, tools=bridge)
    app = FastAPI()

    @app.post("/mcp")
    async def mcp(request: Request):  # type: ignore[no-untyped-def]
        return await endpoint.handle(request, request_id="req-1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def envelope(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    request_id: int | None = 1,
    version: Any = VERSION,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
            },
        },
    }
    if request_id is not None:
        body["id"] = request_id
    return body


def headers_for(body: dict[str, Any], **overrides: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": VERSION,
        "Mcp-Method": body.get("method", ""),
    }
    name = body.get("params", {}).get("name")
    if name is not None:
        headers["Mcp-Name"] = name
    headers.update(overrides)
    return headers


async def post(client: AsyncClient, body: Any, headers: dict[str, str]) -> Any:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return await client.post("/mcp", content=raw, headers=headers)


# ---------- 鉴权先于解析 ----------


async def test_missing_bearer_returns_401_without_parsing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed: list[bytes] = []
    real = mcp_server.decode_jsonrpc_body
    monkeypatch.setattr(
        mcp_server, "decode_jsonrpc_body", lambda raw: parsed.append(raw) or real(raw)
    )

    response = await client.post(
        "/mcp", content=b"{malformed", headers={"MCP-Protocol-Version": VERSION}
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert parsed == []


async def test_invalid_token_returns_401_without_parsing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed: list[bytes] = []
    monkeypatch.setattr(mcp_server, "decode_jsonrpc_body", lambda raw: parsed.append(raw))

    response = await client.post(
        "/mcp", content=b"{malformed", headers={"Authorization": "Bearer nope"}
    )

    assert response.status_code == 401
    assert "invalid_token" in response.headers["www-authenticate"]
    assert parsed == []


async def test_browser_session_id_is_not_a_credential(client: AsyncClient) -> None:
    body = envelope("tools/list")
    headers = headers_for(body)
    del headers["Authorization"]
    headers["X-Session-Id"] = TOKEN

    response = await post(client, body, headers)

    assert response.status_code == 401


async def test_non_bearer_scheme_rejected(client: AsyncClient) -> None:
    body = envelope("tools/list")

    response = await post(client, body, headers_for(body, Authorization=f"Basic {TOKEN}"))

    assert response.status_code == 401


async def test_every_request_is_verified_again(client: AsyncClient, verifier: FakeVerifier) -> None:
    body = envelope("tools/list")
    await post(client, body, headers_for(body))
    await post(client, body, headers_for(body))

    assert verifier.calls == 2


# ---------- 协议头与正文 ----------


async def test_wrong_protocol_version_header_rejected(client: AsyncClient) -> None:
    body = envelope("tools/list")

    response = await post(client, body, headers_for(body, **{"MCP-Protocol-Version": "2025-06-18"}))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == HEADER_MISMATCH


async def test_unsupported_protocol_version_rejected(client: AsyncClient) -> None:
    body = envelope("tools/list", version="2025-06-18")

    response = await post(client, body, headers_for(body, **{"MCP-Protocol-Version": "2025-06-18"}))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == UNSUPPORTED_PROTOCOL_VERSION
    assert error["data"]["supported"] == [VERSION]


async def test_legacy_initialize_handshake_rejected(client: AsyncClient) -> None:
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}},
    }

    response = await post(client, body, headers_for(body, **{"MCP-Protocol-Version": "2025-06-18"}))

    payload = response.json()
    assert "result" not in payload
    assert payload["error"]["code"] in {UNSUPPORTED_PROTOCOL_VERSION, INVALID_PARAMS}


async def test_header_body_method_mismatch_rejected(client: AsyncClient) -> None:
    body = envelope("tools/call", {"name": "query_metrics", "arguments": {}})

    response = await post(client, body, headers_for(body, **{"Mcp-Method": "tools/list"}))

    assert response.json()["error"]["code"] == HEADER_MISMATCH


async def test_header_body_name_mismatch_rejected(client: AsyncClient, bridge: FakeBridge) -> None:
    body = envelope("tools/call", {"name": "query_metrics", "arguments": {}})

    response = await post(client, body, headers_for(body, **{"Mcp-Name": "search_rules"}))

    assert response.json()["error"]["code"] == HEADER_MISMATCH
    assert bridge.calls == []


async def test_duplicated_routing_header_rejected(client: AsyncClient) -> None:
    body = envelope("tools/list")
    raw_headers = [*headers_for(body).items(), ("Mcp-Method", "tools/call")]

    response = await client.post("/mcp", content=json.dumps(body).encode(), headers=raw_headers)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == HEADER_MISMATCH


async def test_malformed_json_after_auth_is_parse_error(client: AsyncClient) -> None:
    response = await client.post(
        "/mcp",
        content=b"{malformed",
        headers={"Authorization": f"Bearer {TOKEN}", "MCP-Protocol-Version": VERSION},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == PARSE_ERROR


async def test_batch_request_rejected(client: AsyncClient) -> None:
    body = [envelope("tools/list")]

    response = await post(client, body, headers_for(envelope("tools/list")))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == INVALID_REQUEST


async def test_notification_is_accepted_without_body(client: AsyncClient) -> None:
    body = envelope("notifications/cancelled", {"requestId": 1}, request_id=None)

    response = await post(client, body, headers_for(body))

    assert response.status_code == 202
    assert response.content == b""


async def test_mcp_session_id_never_issued(client: AsyncClient) -> None:
    body = envelope("tools/list")

    response = await post(client, body, headers_for(body, **{"Mcp-Session-Id": "abc"}))

    assert response.status_code == 200
    assert "mcp-session-id" not in {key.lower() for key in response.headers}


async def test_unknown_method_is_json_rpc_error(client: AsyncClient) -> None:
    body = envelope("resources/list")

    response = await post(client, body, headers_for(body))

    assert response.json()["error"]["code"] == METHOD_NOT_FOUND


# ---------- 分发 ----------


async def test_server_discover_advertises_only_tools(client: AsyncClient) -> None:
    body = envelope("server/discover")

    result = (await post(client, body, headers_for(body))).json()["result"]

    assert result["supportedVersions"] == [VERSION]
    assert set(result["capabilities"]) == {"tools"}
    assert result["cacheScope"] == "private"


async def test_tools_list_uses_bridge_descriptors(client: AsyncClient) -> None:
    body = envelope("tools/list")

    result = (await post(client, body, headers_for(body))).json()["result"]

    assert [tool["name"] for tool in result["tools"]] == ["query_metrics"]
    assert result["cacheScope"] == "private"
    assert result["resultType"] == "complete"


async def test_tools_call_returns_structured_and_text_content(client: AsyncClient) -> None:
    body = envelope("tools/call", {"name": "query_metrics", "arguments": {"metric": "gross_gmv"}})

    result = (await post(client, body, headers_for(body))).json()["result"]

    assert result["structuredContent"] == {"metric": "gross_gmv", "value": "42.00"}
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert result.get("isError") in (None, False)


async def test_tool_errors_are_json_rpc_errors(client: AsyncClient) -> None:
    body = envelope(
        "tools/call", {"name": "query_metrics", "arguments": {"metric": "not_a_metric"}}
    )

    payload = (await post(client, body, headers_for(body))).json()

    assert payload["jsonrpc"] == "2.0" and payload["id"] == 1
    assert payload["error"]["code"] == INVALID_PARAMS
    assert "request_id" not in payload  # 不是 v2 ErrorResponse


# ---------- 审查整改（F2、F5） ----------


class BrokenVerifier:
    async def verify(self, token: str) -> McpPrincipal | None:
        raise ConnectionError("database down")


class ExplodingBridge(FakeBridge):
    def list_tools(self, principal: McpPrincipal) -> list[McpToolDescriptor]:
        raise RuntimeError("boom")


async def _client_with(verifier: Any, bridge: Any) -> AsyncClient:
    endpoint = McpEndpoint(verifier=verifier, tools=bridge)
    app = FastAPI()

    @app.post("/mcp")
    async def mcp(request: Request):  # type: ignore[no-untyped-def]
        return await endpoint.handle(request, request_id="req-1")

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_credential_store_failure_is_503_json_rpc_error_without_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed: list[bytes] = []
    monkeypatch.setattr(mcp_server, "decode_jsonrpc_body", lambda raw: parsed.append(raw))
    body = envelope("tools/list")

    async with await _client_with(BrokenVerifier(), FakeBridge()) as http:
        response = await post(http, body, headers_for(body))

    assert response.status_code == 503
    payload = response.json()
    assert payload["jsonrpc"] == "2.0" and payload["id"] is None
    assert "database" not in json.dumps(payload)
    assert parsed == []


async def test_unexpected_dispatch_failure_is_json_rpc_internal_error() -> None:
    body = envelope("tools/list")

    async with await _client_with(FakeVerifier(), ExplodingBridge()) as http:
        response = await post(http, body, headers_for(body))

    assert response.status_code == 200
    assert response.json()["error"]["code"] == INTERNAL_ERROR
    assert "boom" not in response.text


async def test_notification_still_passes_the_header_ladder(client: AsyncClient) -> None:
    body = envelope("notifications/cancelled", {"requestId": 1}, request_id=None)

    response = await post(client, body, headers_for(body, **{"Mcp-Method": "tools/call"}))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == HEADER_MISMATCH
