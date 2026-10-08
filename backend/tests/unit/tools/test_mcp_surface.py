"""MCP 工具面与契约白名单对齐（N5 A Task 0；契约 §8.14.3）。

白名单 `McpReadOnlyTool` 是契约权威，注册表里标 `ToolRole.MCP_READONLY` 的工具是实现。
两者必须**双向相等**：注册表多一个就是越权外发，少一个就是契约未兑现。
"""

from __future__ import annotations

from typing import cast

from app.db.session import Database
from app.schemas.v2.memory import McpReadOnlyTool
from app.tools.customer import build_customer_tools
from app.tools.merchant import build_merchant_tools
from app.tools.registry import build_tool_registry
from app.tools.types import ToolRole, WritePolicy


def _production_registry():
    database = cast(Database, object())
    return build_tool_registry((*build_merchant_tools(database), *build_customer_tools(database)))


def test_mcp_surface_equals_contract_whitelist() -> None:
    names = {spec.name for spec in _production_registry().surface_for_mcp()}
    assert names == {tool.value for tool in McpReadOnlyTool}


def test_mcp_surface_is_merchant_read_only() -> None:
    for spec in _production_registry().surface_for_mcp():
        assert ToolRole.MERCHANT in spec.roles, spec.name
        assert spec.write_policy is WritePolicy.READ_ONLY, spec.name
