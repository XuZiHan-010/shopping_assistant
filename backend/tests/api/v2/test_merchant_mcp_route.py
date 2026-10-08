"""`POST /api/v2/merchant/mcp` 路由层（N5 A Task 2；契约 §8.14.3、§8.14.4）。

只测不需要数据库的边界：方法限制、鉴权前置、OpenAPI 与凭证路径不存在。
真实凭证与标准客户端见 `tests/integration/mcp/`。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.mcp.credentials import McpCredentialStore

PATH = "/api/v2/merchant/mcp"


async def test_get_is_not_allowed(client: AsyncClient) -> None:
    response = await client.get(PATH)

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


async def test_post_without_bearer_is_401_with_challenge(client: AsyncClient) -> None:
    response = await client.post(PATH, content=b"{malformed")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_browser_session_header_is_not_accepted(client: AsyncClient) -> None:
    response = await client.post(PATH, headers={"X-Session-Id": "x" * 43}, content=b"{}")

    assert response.status_code == 401


def test_no_http_route_for_credentials(test_settings: Settings) -> None:
    """2026-09-21 用户裁定：凭证只经命令行签发与撤销，不存在任何 HTTP 路径。"""

    # 当前 FastAPI 把 include_router 的子路由折叠进惰性结构，`app.routes` 读不全；以 OpenAPI 为准。
    paths = set(create_app(test_settings).openapi()["paths"])
    assert not [path for path in paths if "credential" in path or "mcp/token" in path]
    assert PATH in paths


def test_openapi_documents_mcp_route_without_session_header(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    operation = schema["paths"][PATH]["post"]

    assert "get" not in schema["paths"][PATH]
    header_names = {
        parameter["name"].lower()
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "header"
    }
    assert "x-session-id" not in header_names
    assert "401" in operation["responses"]


async def test_rotating_bearer_tokens_does_not_escape_the_rate_limit(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """鉴权前的限流只按来源计：每次换一个伪造 token 不能换出新桶，也不能撑满全站共享的限流表。"""

    async def reject(self: object, token: str) -> None:
        return None

    monkeypatch.setattr(McpCredentialStore, "verify", reject)
    app = create_app(test_settings.model_copy(update={"rate_limit_per_minute": 3}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        statuses = [
            (
                await http.post(
                    PATH, headers={"Authorization": f"Bearer forged-{i}"}, content=b"{}"
                )
            ).status_code
            for i in range(4)
        ]

    assert statuses == [401, 401, 401, 429]
    assert len(app.state.rate_limiter._windows) == 1


def test_no_credential_route_even_hidden_from_openapi() -> None:
    """`include_in_schema=False` 的路由不进 OpenAPI；直接扫源码里的路由装饰器（审查 G1）。"""

    import re
    from pathlib import Path

    decorator = re.compile(
        r"@\w*router\.(?:api_route|get|post|put|patch|delete)\(\s*[\"']([^\"']*)"
    )
    app_root = Path(__file__).resolve().parents[3] / "app"
    paths = [
        match.group(1)
        for source in app_root.rglob("*.py")
        for match in decorator.finditer(source.read_text(encoding="utf-8"))
    ]

    assert "/mcp" in paths  # 扫描本身有效
    assert not [path for path in paths if "credential" in path or "token" in path]
