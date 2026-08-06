"""AppError 与限流命中都会被记入 OperationalMetrics。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_chat_service
from app.core.config import AppEnvironment, Settings
from app.core.errors import DatabaseUnavailableError
from app.main import create_app
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_ONE_TOKEN

AUTH = {"Authorization": f"Bearer {MERCHANT_ONE_TOKEN}"}


def _unavailable_chat_service() -> object:
    raise DatabaseUnavailableError()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+psycopg://user:pass@localhost/test",
        "frontend_origin": "http://localhost:5173",
        "rate_limit_per_minute": 1_000,
    }
    base.update(overrides)
    return Settings(**base)


@pytest.mark.asyncio
async def test_auth_required_error_is_recorded_in_error_code_counts() -> None:
    app = create_app(_settings())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/chat",
            json={"message": "hi", "client_request_id": "req-1"},
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 401
    assert app.state.metrics.error_code_counts.get("AUTH_REQUIRED") == 1


@pytest.mark.asyncio
async def test_rate_limited_error_increments_both_dedicated_and_generic_counters() -> None:
    settings = _settings(
        rate_limit_per_minute=1,
        demo_merchant_tokens={MERCHANT_ONE_TOKEN: MERCHANT_ONE_ID},
    )
    app = create_app(settings)
    app.dependency_overrides[get_chat_service] = _unavailable_chat_service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        payload = {"message": "hi", "client_request_id": "req-a"}
        await client.post("/api/chat", json=payload, headers={**AUTH, "Accept": "application/json"})
        second = await client.post(
            "/api/chat",
            json={**payload, "client_request_id": "req-b"},
            headers={**AUTH, "Accept": "application/json"},
        )

    assert second.status_code == 429
    assert app.state.metrics.rate_limit_hits == 1
    assert app.state.metrics.error_code_counts.get("RATE_LIMITED") == 1
