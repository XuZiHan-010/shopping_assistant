"""端到端验证：伪造转发头无法绕过限流（§B7 必测）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_chat_service
from app.core.config import AppEnvironment, Settings
from app.core.errors import DatabaseUnavailableError
from app.main import create_app
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_ONE_TOKEN

AUTH = {"Authorization": f"Bearer {MERCHANT_ONE_TOKEN}"}


def _unavailable_chat_service() -> object:
    """让首个请求在限流依赖之后快速结束，不访问真实数据库或 LLM。"""

    raise DatabaseUnavailableError()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+psycopg://user:pass@localhost/test",
        "frontend_origin": "http://localhost:5173",
        "demo_merchant_tokens": {MERCHANT_ONE_TOKEN: MERCHANT_ONE_ID},
        "rate_limit_per_minute": 1,
    }
    base.update(overrides)
    return Settings(**base)


@pytest_asyncio.fixture
async def untrusted_client() -> AsyncIterator[AsyncClient]:
    app = create_app(_settings(trusted_proxy_hops=0))
    app.dependency_overrides[get_chat_service] = _unavailable_chat_service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_varying_forwarded_for_does_not_reset_limit(untrusted_client: AsyncClient) -> None:
    payload = {"message": "hi", "client_request_id": "req-a"}

    first = await untrusted_client.post(
        "/api/chat",
        json=payload,
        headers={**AUTH, "Accept": "application/json", "X-Forwarded-For": "1.1.1.1"},
    )
    second = await untrusted_client.post(
        "/api/chat",
        json={**payload, "client_request_id": "req-b"},
        headers={**AUTH, "Accept": "application/json", "X-Forwarded-For": "2.2.2.2"},
    )

    assert first.status_code != 429
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


@pytest_asyncio.fixture
async def trusted_proxy_client() -> AsyncIterator[AsyncClient]:
    app = create_app(_settings(trusted_proxy_hops=1, trusted_proxy_ips="127.0.0.1"))
    app.dependency_overrides[get_chat_service] = _unavailable_chat_service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_trusted_chain_separates_distinct_downstream_clients(
    trusted_proxy_client: AsyncClient,
) -> None:
    payload = {"message": "hi", "client_request_id": "req-c"}

    first = await trusted_proxy_client.post(
        "/api/chat",
        json=payload,
        headers={**AUTH, "Accept": "application/json", "X-Forwarded-For": "198.51.100.1"},
    )
    second = await trusted_proxy_client.post(
        "/api/chat",
        json={**payload, "client_request_id": "req-d"},
        headers={**AUTH, "Accept": "application/json", "X-Forwarded-For": "198.51.100.2"},
    )

    assert first.status_code != 429
    assert second.status_code != 429
