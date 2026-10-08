"""`POST /api/v2/merchant/mcp`：外部 MCP 客户端的只读入口（PRD A8、S8；契约 §8.14.3、§8.14.4）。

鉴权只认 `Authorization: Bearer <MCP access token>`，**不挂 `X-Session-Id` 依赖**：
浏览器会话不交给第三方。
协议、鉴权顺序与工具投影都在 `app/mcp/`；本模块只装配依赖。不支持 GET（405，`Allow: POST`）。
凭证没有任何 HTTP 路径，只经 `scripts/mcp_credentials.py` 签发与撤销。
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import (
    enforce_keyed_rate_limit,
    get_app_settings,
    get_database,
    get_principal_secret,
)
from app.api.routes.v2.chat_stream import build_gates
from app.core.config import Settings
from app.db.session import Database
from app.mcp.credentials import McpCredentialStore
from app.mcp.server import PROTOCOL_VERSION, McpEndpoint
from app.mcp.tools import RegistryToolBridge

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-mcp"])

_JSON_RPC_BODY: Final[dict[str, Any]] = {
    "type": "object",
    "description": f"JSON-RPC 2.0 单请求；MCP 协议版本 {PROTOCOL_VERSION}（官方 SDK 协议类型）",
}


@router.get("/mcp", include_in_schema=False)
async def get_merchant_mcp() -> Response:
    """2026-07-28 无协议会话，没有服务端推送流：GET 一律 405（契约 §8.14.3）。"""

    return Response(status_code=405, headers={"Allow": "POST"})


@router.post(
    "/mcp",
    summary="MCP 只读服务入口",
    description=(
        f"协议固定 `{PROTOCOL_VERSION}`，无协议会话的 Streamable HTTP：不实现旧版 `initialize`，"
        "不接收也不签发 `Mcp-Session-Id`。只支持 `server/discover`、`tools/list`、`tools/call`；"
        "工具面为只读白名单与凭证 scope 的交集。凭证缺失或无效时在解析正文之前返回 401。"
        "其余错误一律为 JSON-RPC error，不使用 v2 `ErrorResponse`。"
    ),
    response_class=Response,
    responses={
        200: {
            "description": "JSON-RPC result 或 JSON-RPC error",
            "content": {"application/json": {"schema": _JSON_RPC_BODY}},
        },
        202: {"description": "通知已接收（无正文）"},
        400: {"description": "解析失败、请求头与正文不一致或协议版本不受支持（JSON-RPC error）"},
        401: {"description": "MCP 凭证缺失、无效、过期或已撤销；带 `WWW-Authenticate: Bearer`"},
        413: {"description": "请求正文过大（JSON-RPC error）"},
        429: {"description": "请求过于频繁"},
        503: {
            "description": "凭证库不可用、无法鉴权（`id: null` 的 JSON-RPC error，不解析请求正文）"
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": _JSON_RPC_BODY}},
        },
        "parameters": [
            {
                "name": "MCP-Protocol-Version",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "enum": [PROTOCOL_VERSION]},
            },
            {"name": "Mcp-Method", "in": "header", "required": True, "schema": {"type": "string"}},
            {"name": "Mcp-Name", "in": "header", "required": False, "schema": {"type": "string"}},
        ],
    },
)
async def post_merchant_mcp(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
) -> Response:
    # 限流在鉴权之前、且只按来源计：键是固定的 "mcp" + 客户端 IP。若把 Authorization 放进键，
    # 每换一个伪造 token 就是一个新桶，既绕过限流，又能撑满全站共享的限流表（审查 F1）。
    enforce_keyed_rate_limit(request, settings, key="mcp")
    endpoint = McpEndpoint(
        verifier=McpCredentialStore(database),
        tools=RegistryToolBridge(build_gates(request, database, principal_secret)),
    )
    return await endpoint.handle(request, request_id=str(request.state.request_id))
