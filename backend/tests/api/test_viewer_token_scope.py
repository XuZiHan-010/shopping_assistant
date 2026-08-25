"""只读令牌的端点级边界：GET 端点两把钥匙都认，写端点只认管理员令牌。

拒绝路径（401/403）不需要真实数据库——鉴权依赖在触碰 DB 之前就短路返回
（`get_db_session` 只构造 `AsyncSession` 对象，不在此处发起真实连接）。

「GET 端点确实接了 `require_admin_or_viewer_token`」这一半用源码检查断言
（与 `tests/unit/knowledge/test_admin_boundaries.py` 同一种做法）：验证令牌真的
能读到数据需要真实 Postgres 才能让 handler 跑完整条查询路径，属于
`tests/api/test_knowledge_tree.py`、`tests/api/test_chatbi_analytics.py` 已经
覆盖的集成测试范畴，这里不重复。
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import AppEnvironment, Settings
from app.main import create_app

ADMIN_TOKEN = "test-only-admin-token-value"
VIEWER_TOKEN = "test-only-viewer-token-value"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@127.0.0.1:1/nonexistent",
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
        viewer_token=VIEWER_TOKEN,
    )
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


WRITE_ENDPOINTS = (
    ("POST", "/api/admin/knowledge/documents"),
    ("POST", "/api/admin/knowledge/business-domains"),
    ("POST", "/api/admin/knowledge/memories/compress"),
    ("POST", "/api/admin/reports/daily/recompute"),
    ("POST", "/api/admin/analytics/chatbi/rollup"),
)

READ_ONLY_ADMIN_ENDPOINTS = ("/api/admin/ops/status",)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), WRITE_ENDPOINTS)
async def test_viewer_token_rejected_on_write_endpoints(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path, headers={"X-Admin-Token": VIEWER_TOKEN})

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("path", READ_ONLY_ADMIN_ENDPOINTS)
async def test_viewer_token_rejected_on_admin_only_reads(client: AsyncClient, path: str) -> None:
    """`ops/status` 暴露预算余量、限流命中等运维内情，只读角色不该看到。"""

    response = await client.get(path, headers={"X-Admin-Token": VIEWER_TOKEN})

    assert response.status_code == 403


def _dependency_names(source: str, function_name: str) -> set[str]:
    """提取某个路由函数签名里 `Depends(...)` 括号内的可调用名。"""

    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == function_name
    )
    names: set[str] = set()
    for call in ast.walk(func):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "Depends"
            and call.args
            and isinstance(call.args[0], ast.Name)
        ):
            names.add(call.args[0].id)
    return names


@pytest.mark.parametrize(
    ("file", "function_name"),
    [
        ("app/api/routes/knowledge.py", "get_knowledge_tree"),
        ("app/api/routes/knowledge.py", "get_document"),
        ("app/api/routes/analytics.py", "chatbi_overview"),
        ("app/api/routes/analytics.py", "chatbi_categories"),
    ],
)
def test_get_endpoints_accept_viewer_token(file: str, function_name: str) -> None:
    source = Path(file).read_text(encoding="utf-8")

    assert "require_admin_or_viewer_token" in _dependency_names(source, function_name)


@pytest.mark.parametrize(
    ("file", "function_name"),
    [
        ("app/api/routes/knowledge.py", "create_document"),
        ("app/api/routes/knowledge.py", "update_document"),
        ("app/api/routes/knowledge.py", "delete_document"),
        ("app/api/routes/knowledge.py", "create_business_domain"),
        ("app/api/routes/knowledge.py", "rename_business_domain"),
        ("app/api/routes/knowledge.py", "delete_business_domain"),
        ("app/api/routes/knowledge.py", "compress_memory"),
        ("app/api/routes/analytics.py", "chatbi_rollup"),
    ],
)
def test_write_endpoints_stay_admin_only(file: str, function_name: str) -> None:
    source = Path(file).read_text(encoding="utf-8")

    dependencies = _dependency_names(source, function_name)
    assert "require_admin_token" in dependencies
    assert "require_admin_or_viewer_token" not in dependencies
