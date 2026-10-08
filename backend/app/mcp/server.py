"""`POST /api/v2/merchant/mcp` 的协议层（PRD A8；契约 §8.14.3）。

处理顺序固定，**先鉴权再碰正文**：

1. `Authorization: Bearer <MCP access token>`；缺失或无效 → HTTP 401 + `WWW-Authenticate`，
   不读、不解析正文。
   每次请求都查库校验，不缓存（撤销后下一次请求立即失效）。
2. 正文按 JSON-RPC 2.0 单请求解析；协议版本固定 `2026-07-28`，`MCP-Protocol-Version`、`Mcp-Method`、
   `Mcp-Name` 与正文一致性用官方 SDK 的入站校验阶梯（`mcp.shared.inbound`）判定。
3. 分发 `server/discover`、`tools/list`、`tools/call`；其余方法与旧版 `initialize`
   一律 JSON-RPC error。

请求与响应直接用官方 SDK 的 2026-07-28 协议类型，不另造信封。
无协议会话：不接收也不签发 `Mcp-Session-Id`。
工具面与执行由 `ToolBridge` 提供（`app/mcp/tools.py`），本模块不认识任何具体工具。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final, Protocol

from fastapi import Request, Response
from mcp.shared.inbound import (
    InboundLadderRejection,
    classify_inbound_request,
    find_duplicated_routing_header,
)
from mcp_types import _v2026_07_28 as wire
from mcp_types.jsonrpc import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
)
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel

from app.mcp.credentials import McpPrincipal

logger = logging.getLogger(__name__)

PROTOCOL_VERSION: Final = "2026-07-28"
SUPPORTED_VERSIONS: Final[tuple[str, ...]] = (PROTOCOL_VERSION,)
MAX_BODY_BYTES: Final = 256 * 1024
"""只读工具的参数都很小；上限防止未分页的大正文占内存。"""

_REALM: Final = 'Bearer realm="borough-mcp"'
_JSON: Final = "application/json"

if PROTOCOL_VERSION not in MODERN_PROTOCOL_VERSIONS:  # pragma: no cover - SDK 升级时的护栏
    raise RuntimeError(f"所钉 MCP SDK 不支持协议版本 {PROTOCOL_VERSION}")


@dataclass(frozen=True)
class McpToolDescriptor:
    name: str
    description: str
    input_schema: Mapping[str, Any]


class McpToolError(Exception):
    """工具层失败：转成 JSON-RPC error 返回，不包装成 v2 `ErrorResponse`。"""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class CredentialVerifier(Protocol):
    async def verify(self, token: str) -> McpPrincipal | None: ...


class ToolBridge(Protocol):
    def list_tools(self, principal: McpPrincipal) -> list[McpToolDescriptor]: ...

    async def call_tool(
        self,
        principal: McpPrincipal,
        name: str,
        arguments: Mapping[str, Any],
        *,
        request_id: str,
    ) -> Any: ...


class _JsonRpcFailure(Exception):
    def __init__(self, status: HTTPStatus, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.data = data


def decode_jsonrpc_body(raw: bytes) -> Any:
    """正文解析：只在鉴权通过之后调用（测试以此确认未认证请求碰不到解析器）。"""

    return json.loads(raw)


def _bearer_token(request: Request) -> str | None:
    values = request.headers.getlist("authorization")
    if len(values) != 1:
        return None
    scheme, _, token = values[0].partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token


def _unauthorized(*, invalid: bool) -> Response:
    challenge = f'{_REALM}, error="invalid_token"' if invalid else _REALM
    return Response(status_code=HTTPStatus.UNAUTHORIZED, headers={"WWW-Authenticate": challenge})


def _error_body(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _json_response(payload: Mapping[str, Any], status: HTTPStatus = HTTPStatus.OK) -> Response:
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        status_code=status,
        media_type=_JSON,
    )


def _wire(model: type[BaseModel], fields: Mapping[str, Any]) -> dict[str, Any]:
    """按线上字段名经 SDK 协议类型校验后再序列化：字段缺漏在这里失败，而不是发给客户端。"""

    validated = model.model_validate(dict(fields))
    return validated.model_dump(mode="json", by_alias=True, exclude_none=True)


class McpEndpoint:
    def __init__(self, *, verifier: CredentialVerifier, tools: ToolBridge) -> None:
        self._verifier = verifier
        self._tools = tools

    async def handle(self, request: Request, *, request_id: str) -> Response:
        token = _bearer_token(request)
        if token is None:
            return _unauthorized(invalid=False)
        try:
            principal = await self._verifier.verify(token)
        except Exception:
            # 凭证库不可用时无法鉴权：明确 503，不解析正文、不外泄异常细节（审查 F2）。
            logger.exception("mcp_credential_verify_failed request_id=%s", request_id)
            return _json_response(
                _error_body(None, INTERNAL_ERROR, "凭证校验暂不可用，请稍后重试"),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        if principal is None:
            return _unauthorized(invalid=True)

        message_id: Any = None
        try:
            body = await self._read_body(request)
            message_id = body.get("id")
            # 通知同样先过协议头阶梯，再确认（审查 F5）。
            self._check_ladder(request, body)
            if "id" not in body:
                # 2026-07-28 没有定义客户端到服务端的通知；收到也只确认，不处理。
                return Response(status_code=HTTPStatus.ACCEPTED)
            try:
                result = await self._dispatch(principal, body, request_id=request_id)
            except _JsonRpcFailure:
                raise
            except Exception as error:
                # 解析之后的意外都以 JSON-RPC error 答复，不落到全局 500（审查 F2）。
                logger.exception("mcp_dispatch_failed request_id=%s", request_id)
                raise _JsonRpcFailure(HTTPStatus.OK, INTERNAL_ERROR, "服务内部错误") from error
        except _JsonRpcFailure as failure:
            return _json_response(
                _error_body(message_id, failure.code, failure.message, failure.data),
                failure.status,
            )
        return _json_response({"jsonrpc": "2.0", "id": message_id, "result": result})

    async def _read_body(self, request: Request) -> dict[str, Any]:
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY_BYTES:
                raise _JsonRpcFailure(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE, INVALID_REQUEST, "请求正文过大"
                )
        try:
            body = decode_jsonrpc_body(bytes(raw))
        except (ValueError, UnicodeDecodeError) as error:
            raise _JsonRpcFailure(HTTPStatus.BAD_REQUEST, PARSE_ERROR, "Parse error") from error
        if not isinstance(body, dict):
            # 批量请求（数组）不在 2026-07-28 的 Streamable HTTP 范围内。
            raise _JsonRpcFailure(
                HTTPStatus.BAD_REQUEST, INVALID_REQUEST, "只接受单个 JSON-RPC 请求对象"
            )
        if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            raise _JsonRpcFailure(
                HTTPStatus.BAD_REQUEST, INVALID_REQUEST, "不是合法的 JSON-RPC 2.0 请求"
            )
        return body

    def _check_ladder(self, request: Request, body: Mapping[str, Any]) -> None:
        duplicated = find_duplicated_routing_header(request.headers.items())
        if duplicated is not None:
            raise _JsonRpcFailure(
                HTTPStatus.BAD_REQUEST, HEADER_MISMATCH, f"{duplicated} 请求头重复"
            )
        headers = {key.lower(): value for key, value in request.headers.items()}
        verdict = classify_inbound_request(
            body, headers=headers, supported_modern_versions=SUPPORTED_VERSIONS
        )
        if isinstance(verdict, InboundLadderRejection):
            raise _JsonRpcFailure(
                HTTPStatus.BAD_REQUEST, verdict.code, verdict.message, verdict.data
            )

    async def _dispatch(
        self, principal: McpPrincipal, body: Mapping[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        method = body["method"]
        params = body.get("params")
        params = params if isinstance(params, Mapping) else {}
        if method == "server/discover":
            return _wire(
                wire.DiscoverResult,
                {
                    "supportedVersions": list(SUPPORTED_VERSIONS),
                    "capabilities": {"tools": {}},
                    "cacheScope": "private",
                    "ttlMs": 0,
                    "resultType": "complete",
                },
            )
        if method == "tools/list":
            tools = [
                {
                    "name": descriptor.name,
                    "description": descriptor.description,
                    "inputSchema": dict(descriptor.input_schema),
                }
                for descriptor in self._tools.list_tools(principal)
            ]
            # 工具面随凭证 scope 而变，只能在同一授权上下文内缓存。
            return _wire(
                wire.ListToolsResult,
                {"tools": tools, "cacheScope": "private", "ttlMs": 0, "resultType": "complete"},
            )
        if method == "tools/call":
            return await self._call_tool(principal, params, request_id=request_id)
        raise _JsonRpcFailure(HTTPStatus.OK, METHOD_NOT_FOUND, "Method not found")

    async def _call_tool(
        self, principal: McpPrincipal, params: Mapping[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, Mapping):
            raise _JsonRpcFailure(
                HTTPStatus.OK, INVALID_PARAMS, "tools/call 需要 name 与 arguments 对象"
            )
        try:
            payload = await self._tools.call_tool(principal, name, arguments, request_id=request_id)
        except McpToolError as error:
            raise _JsonRpcFailure(HTTPStatus.OK, error.code, error.message, error.data) from error
        except Exception as error:  # 工具内部异常不外泄细节
            logger.exception("mcp_tool_call_failed tool=%s request_id=%s", name, request_id)
            raise _JsonRpcFailure(HTTPStatus.OK, INTERNAL_ERROR, "工具执行失败") from error
        text = json.dumps(payload, ensure_ascii=False, default=str)
        return _wire(
            wire.CallToolResult,
            {
                "content": [{"type": "text", "text": text}],
                "structuredContent": json.loads(text),
                "resultType": "complete",
            },
        )
