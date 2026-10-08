"""S8：标准 MCP 客户端集成测试（N5 A Task 4；PRD A8、S8、§12.5；契约 §8.14.3）。

用**官方 MCP Python SDK 客户端**、显式钉协议版本 `2026-07-28`，
经真实 HTTP 栈（ASGI）连本地 backend，
不经过任何 LLM：

脚本签发 24 小时、限 `query_metrics` 的凭证 → `tools/list`
→ `tools/call query_metrics(gross_gmv, 近 7 天)`
→ 同一时刻用商家工作台走的同一套工具闸门调用同一指标 → 数值、数据截至时间、指标定义版本逐项一致
→ 撤销凭证 → 下一次调用收到 401。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx2
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.knowledge.index_versions import INDEX_FALLBACK_REASON
from app.mcp.credentials import McpCredentialStore
from app.repositories.audit import AuditRepository
from app.services.v2.drafts import DatabaseDraftSink
from app.tools.gates import AuditRepositorySecurityAudit, DatabaseProvenanceStore, ToolGates
from app.tools.types import ToolContext
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import seed_paid_order, seed_product

pytestmark = pytest.mark.integration

URL = "http://testserver/api/v2/merchant/mcp"
VERSION = "2026-07-28"


def _database(app: FastAPI) -> Database:
    database: Database = app.state.database
    return database


def _window() -> dict[str, str]:
    today = datetime.now(UTC).date()
    return {"start": (today - timedelta(days=7)).isoformat(), "end": today.isoformat()}


@pytest.fixture
async def seeded(postgres_app: FastAPI) -> None:
    database = _database(postgres_app)
    mine = await seed_product(database, MERCHANT_ONE_ID)
    await seed_paid_order(database, MERCHANT_ONE_ID, mine, quantity=3, days_ago=2)
    # 另一家店的成交额不同：若 MCP 绕开了商家注入，数字会对不上。
    theirs = await seed_product(database, MERCHANT_TWO_ID)
    await seed_paid_order(database, MERCHANT_TWO_ID, theirs, quantity=11, days_ago=2)


def _mcp_client(app: FastAPI, token: str) -> Client:
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    )
    transport = streamable_http_client(URL, http_client=http, terminate_on_close=False)
    return Client(transport, mode=VERSION)


@pytest.fixture
async def token(postgres_app: FastAPI, seeded: None) -> AsyncIterator[str]:
    issued = await McpCredentialStore(_database(postgres_app)).issue(
        merchant_id=MERCHANT_ONE_ID, scopes={"query_metrics"}, ttl=timedelta(hours=24)
    )
    yield issued.token


async def _workbench_query(app: FastAPI, merchant_id: UUID, arguments: dict[str, str]) -> Any:
    """商家工作台的取数路径：同一注册表、同一套 ToolGates、商家会话主体。"""

    database = _database(app)
    gates = ToolGates(
        app.state.tool_registry,
        provenance=DatabaseProvenanceStore(database),
        principal_secret=b"workbench-test-secret-0123456789",
        audit=AuditRepositorySecurityAudit(AuditRepository(database)),
        drafts=DatabaseDraftSink(database),
    )
    ctx = ToolContext(
        session=SessionContext(
            session_record_id=UUID(int=42),
            role=SessionRole.MERCHANT,
            merchant_id=merchant_id,
            buyer_key=None,
            shop_slug=None,
        ),
        conversation_id="workbench",
        request_id="workbench-req",
    )
    result = await gates.invoke(ctx, "query_metrics", arguments)
    assert result.ok, result.summary
    return result.payload


async def test_tools_list_is_scoped_by_credential(postgres_app: FastAPI, token: str) -> None:
    async with _mcp_client(postgres_app, token) as client:
        listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["query_metrics"]


async def test_s8_mcp_matches_workbench_and_revocation_is_immediate(
    postgres_app: FastAPI, postgres_client: AsyncClient, token: str
) -> None:
    arguments = {"metric": "gross_gmv", **_window()}

    async with _mcp_client(postgres_app, token) as client:
        result = await client.call_tool("query_metrics", arguments)
    assert not result.is_error
    via_mcp = result.structured_content
    via_workbench = await _workbench_query(postgres_app, MERCHANT_ONE_ID, arguments)

    assert isinstance(via_mcp, dict)
    for field in ("value", "data_cutoff", "definition_version", "metric", "source"):
        assert field in via_workbench, (field, via_workbench)
        assert via_mcp[field] == _jsonable(via_workbench[field]), field
    # 只看到本店：另一家店的成交额更大，不能混进来。
    other_shop = await _workbench_query(postgres_app, MERCHANT_TWO_ID, arguments)
    assert via_mcp["value"] != _jsonable(other_shop["value"])

    store = McpCredentialStore(_database(postgres_app))
    (summary,) = await store.list()
    assert await store.revoke(summary.credential_id)

    async with _mcp_client(postgres_app, token) as client:
        with pytest.raises(MCPError):
            await client.call_tool("query_metrics", arguments)
    raw = await postgres_client.post(
        "/api/v2/merchant/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "MCP-Protocol-Version": VERSION,
            "Mcp-Method": "tools/list",
        },
        content=b"{}",
    )
    assert raw.status_code == 401


async def test_write_tool_is_not_callable_by_name(postgres_app: FastAPI, token: str) -> None:
    async with _mcp_client(postgres_app, token) as client:
        with pytest.raises(MCPError):
            await client.call_tool("draft_restock", {"product_id": str(UUID(int=1)), "delta": 1})


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    plain = str | int | float | bool | type(None) | dict | list
    return value if isinstance(value, plain) else str(value)


async def test_degraded_retrieval_is_visible_to_mcp_clients(postgres_app: FastAPI) -> None:
    """R7：索引降级为纯关键词时，MCP 输出同样带出降级来源，不把兜底当完整检索（审查 F3）。"""

    issued = await McpCredentialStore(_database(postgres_app)).issue(
        merchant_id=MERCHANT_ONE_ID, scopes={"search_rules"}, ttl=timedelta(hours=1)
    )
    async with _mcp_client(postgres_app, issued.token) as client:
        result = await client.call_tool("search_rules", {"query": "退货运费由谁承担"})

    payload = result.structured_content
    assert isinstance(payload, dict)
    assert payload["retrieval"] == "KEYWORD_ONLY"
    assert payload["index_degraded_reason"] == INDEX_FALLBACK_REASON
