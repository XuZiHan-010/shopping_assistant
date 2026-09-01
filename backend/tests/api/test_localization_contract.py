"""`Accept-Language` / `Content-Language` HTTP 边界契约测试。

覆盖 `docs/backend-development-plan.md` §8.6.1：所有成功和错误响应都
回显 `Content-Language`，GET 响应带 `Vary: Accept-Language`；业务
`AppError`、Pydantic validation、404、`AUTH_REQUIRED` 都不得在英语响应里
夹带中文原句。这里只用 `client`/自建的免数据库 Settings 驱动请求——
`/api/health`、路径校验失败、鉴权失败都发生在触达数据库之前，不需要真实
PostgreSQL（本地开发环境当前也没有 Docker Desktop 可用）。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from uuid import UUID

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import AppEnvironment, Settings
from app.main import create_app

MERCHANT_TOKEN = "localization-contract-test-token"
MERCHANT_ID = UUID("00000000-0000-0000-0000-0000000009a1")

_HAN_PATTERN = re.compile(r"[一-鿿]")


def contains_han(text: str) -> bool:
    return bool(_HAN_PATTERN.search(text))


@pytest_asyncio.fixture
async def authed_client() -> AsyncIterator[AsyncClient]:
    """带一个已配置演示 Token 的免数据库应用，用于鉴权通过后的边界测试。"""

    settings = Settings(
        app_env=AppEnvironment.TEST,
        app_version="0.1.0",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        demo_merchant_tokens={MERCHANT_TOKEN: MERCHANT_ID},
        rate_limit_per_minute=1000,
    )
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as test_client:
        yield test_client


async def test_health_echoes_content_language(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"Accept-Language": "en-US"})

    assert response.headers["Content-Language"] == "en-US"
    assert "Accept-Language" in response.headers["Vary"]


async def test_health_defaults_to_chinese_without_header(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.headers["Content-Language"] == "zh-CN"
    assert "Accept-Language" in response.headers["Vary"]


async def test_health_honors_zh_cn_header(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"Accept-Language": "zh-CN"})

    assert response.headers["Content-Language"] == "zh-CN"


async def test_validation_error_localizes_message_and_headers(
    authed_client: AsyncClient,
) -> None:
    response = await authed_client.get(
        "/api/conversations/not-a-uuid",
        headers={
            "Authorization": f"Bearer {MERCHANT_TOKEN}",
            "Accept-Language": "en-US",
        },
    )

    assert response.status_code == 422
    assert response.headers["Content-Language"] == "en-US"
    body = response.json()
    assert body["code"] == "INVALID_REQUEST"
    assert not contains_han(body["message"])
    assert body["details"], "路径参数校验失败应当带上字段级 details"
    assert all(not contains_han(detail["message"]) for detail in body["details"])


async def test_validation_error_defaults_to_chinese_without_header(
    authed_client: AsyncClient,
) -> None:
    response = await authed_client.get(
        "/api/conversations/not-a-uuid",
        headers={"Authorization": f"Bearer {MERCHANT_TOKEN}"},
    )

    assert response.status_code == 422
    assert response.headers["Content-Language"] == "zh-CN"
    body = response.json()
    assert body["code"] == "INVALID_REQUEST"
    assert contains_han(body["message"])
    assert all(contains_han(detail["message"]) for detail in body["details"])


async def test_replaying_same_failure_in_two_locales_keeps_code_but_changes_message(
    authed_client: AsyncClient,
) -> None:
    """同一失败请求换语言重放：`code` 不变，展示 `message` 必须换语言。"""

    zh_response = await authed_client.get(
        "/api/conversations/not-a-uuid",
        headers={"Authorization": f"Bearer {MERCHANT_TOKEN}", "Accept-Language": "zh-CN"},
    )
    en_response = await authed_client.get(
        "/api/conversations/not-a-uuid",
        headers={"Authorization": f"Bearer {MERCHANT_TOKEN}", "Accept-Language": "en-US"},
    )

    assert zh_response.json()["code"] == en_response.json()["code"] == "INVALID_REQUEST"
    assert zh_response.json()["message"] != en_response.json()["message"]


async def test_auth_required_error_localizes_message(client: AsyncClient) -> None:
    response = await client.get("/api/conversations", headers={"Accept-Language": "en-US"})

    assert response.status_code == 401
    assert response.headers["Content-Language"] == "en-US"
    body = response.json()
    assert body["code"] == "AUTH_REQUIRED"
    assert not contains_han(body["message"])


async def test_auth_required_error_defaults_to_chinese(client: AsyncClient) -> None:
    response = await client.get("/api/conversations")

    assert response.status_code == 401
    assert response.headers["Content-Language"] == "zh-CN"
    assert contains_han(response.json()["message"])


async def test_not_found_route_localizes_message(client: AsyncClient) -> None:
    response = await client.get(
        "/api/this-route-does-not-exist", headers={"Accept-Language": "en-US"}
    )

    assert response.status_code == 404
    assert response.headers["Content-Language"] == "en-US"
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert not contains_han(body["message"])
