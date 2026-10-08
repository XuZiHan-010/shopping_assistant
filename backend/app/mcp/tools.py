"""MCP 工具桥：把工具注册表的只读子集投影给外部客户端（PRD A8；契约 §8.14.3；后端计划 §6.9）。

- 工具面 = `registry.surface_for_mcp()` ∩ 凭证 scope；写工具不在 MCP 工具面里，按名调用也拒绝；
- 执行走与商家会话**同一套** `ToolGates`：`merchant_id` 只从凭证主体注入，模型 / 客户端参数里的
  身份字段由身份闸门拦截并审计——「MCP 与工作台数字一致」因此是结构上的，不是两套实现对齐；
- 输出剥离审批证据、确认令牌（§8.7.9）与图表数据（`chart_data` 只供工作台渲染，§8.7.11）。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Final
from uuid import UUID

from mcp_types.jsonrpc import INTERNAL_ERROR, INVALID_PARAMS

from app.core.session import SessionContext, SessionRole
from app.mcp.credentials import McpPrincipal
from app.mcp.server import McpToolDescriptor, McpToolError
from app.tools.errors import FatalToolError
from app.tools.gates import ToolGates
from app.tools.types import ToolContext, ToolOutcome

#: 无论嵌套在哪一层都不得外发的键。
FORBIDDEN_OUTPUT_KEYS: Final = frozenset({"approval_evidence", "confirmation_token", "chart_data"})

_NOT_AVAILABLE: Final = "工具不存在或不在该凭证的授权范围内"


class _NotPlainData(TypeError):
    pass


def _plain(value: Any) -> Any:
    """先把载荷规整为纯 JSON 数据：常见标量转字符串，其它对象一律拒绝（审查 F4）。

    若对 pydantic 模型、dataclass 之类用 `default=str` 兜底，它们的 repr 会整段变成字符串，
    绕过按键名的剥离；所以这里宁可失败，也不把看不清内容的对象外发。
    """

    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, date):  # datetime 是 date 的子类
        return value.isoformat()
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    raise _NotPlainData(type(value).__name__)


def _scrub(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _scrub(item) for key, item in value.items() if key not in FORBIDDEN_OUTPUT_KEYS
        }
    if isinstance(value, list | tuple):
        return [_scrub(item) for item in value]
    return value


class RegistryToolBridge:
    def __init__(self, gates: ToolGates) -> None:
        self._gates = gates

    def _allowed(self, principal: McpPrincipal) -> dict[str, Any]:
        return {
            spec.name: spec
            for spec in self._gates.registry.surface_for_mcp()
            if spec.name in principal.scopes
        }

    def list_tools(self, principal: McpPrincipal) -> list[McpToolDescriptor]:
        return [
            McpToolDescriptor(
                name=spec.name,
                description=spec.description,
                input_schema=spec.args_model.model_json_schema(),
            )
            for name, spec in sorted(self._allowed(principal).items())
        ]

    async def call_tool(
        self,
        principal: McpPrincipal,
        name: str,
        arguments: Mapping[str, Any],
        *,
        request_id: str,
    ) -> Any:
        if name not in self._allowed(principal):
            # 未授权、写工具与不存在的工具同一答复，不泄露工具是否存在。
            raise McpToolError(INVALID_PARAMS, _NOT_AVAILABLE)
        ctx = ToolContext(
            session=SessionContext(
                session_record_id=principal.credential_id,
                role=SessionRole.MERCHANT,
                merchant_id=principal.merchant_id,
                buyer_key=None,
                shop_slug=None,
            ),
            conversation_id=f"mcp:{principal.credential_id}",
            request_id=request_id,
        )
        try:
            result = await self._gates.invoke(ctx, name, dict(arguments))
        except FatalToolError as error:
            # 闸门已写安全审计；对外只给中性答复。
            raise McpToolError(INVALID_PARAMS, "工具调用被拒绝") from error
        if not result.ok:
            code = (
                INVALID_PARAMS
                if result.outcome is ToolOutcome.INVALID_ARGUMENTS
                else INTERNAL_ERROR
            )
            data = {"reason_code": result.reason_code.value} if result.reason_code else None
            raise McpToolError(code, result.summary or "工具执行失败", data)
        try:
            plain = _plain(result.payload)
        except _NotPlainData as error:
            raise McpToolError(INTERNAL_ERROR, "工具结果无法安全序列化") from error
        return _scrub(plain)
