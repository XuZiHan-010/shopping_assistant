"""GET /api/admin/ops/status：401/403/200/未配置时 404。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import AppEnvironment, Settings
from app.db.session import Database
from app.main import create_app
from tests.conftest import MERCHANT_ONE_TOKEN
from tests.postgres import TRUNCATE_ALL_TABLES

ADMIN_TOKEN = "test-only-admin-token-value"


def _settings_without_admin_token() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )


def _settings_with_admin_token() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
    )


@pytest.mark.asyncio
async def test_route_absent_when_admin_token_not_configured() -> None:
    app = create_app(_settings_without_admin_token())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_header_returns_401() -> None:
    app = create_app(_settings_with_admin_token())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_merchant_token_used_as_admin_header_returns_403() -> None:
    app = create_app(_settings_with_admin_token())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/admin/ops/status", headers={"X-Admin-Token": MERCHANT_ONE_TOKEN}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


@pytest_asyncio.fixture
async def admin_app(migrated_postgres: str) -> AsyncIterator[FastAPI]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
        llm_daily_budget_tokens=5_000,
    )
    database = Database(settings)
    async with database.session() as session:
        await session.execute(text(TRUNCATE_ALL_TABLES))
        await session.execute(text("TRUNCATE TABLE llm_daily_budget CASCADE"))
        await session.commit()
    app = create_app(settings, database=database)
    yield app
    await database.dispose()


@pytest.mark.asyncio
async def test_correct_token_returns_200_with_safe_payload(admin_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "llm_tokens_used_today",
        "llm_tokens_remaining_today",
        "llm_calls_today",
        "rate_limit_hits",
        "degraded_count",
        "error_code_counts",
        "agent_node_average_ms",
    }
    assert body["llm_tokens_used_today"] == 0
    assert body["llm_tokens_remaining_today"] == 5_000
    assert ADMIN_TOKEN not in response.text
    assert "postgresql" not in response.text.lower()
    assert MERCHANT_ONE_TOKEN not in response.text
