from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.db.session import Database
from app.main import create_app


def make_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )


@pytest.mark.asyncio
async def test_ready_returns_ok_when_database_ping_succeeds() -> None:
    settings = make_settings()
    database = Database(settings)
    database.ping = AsyncMock(return_value=None)  # type: ignore[method-assign]
    app = create_app(settings, database=database)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    await database.dispose()


@pytest.mark.asyncio
async def test_ready_hides_database_error_details() -> None:
    settings = make_settings()
    database = Database(settings)
    database.ping = AsyncMock(  # type: ignore[method-assign]
        side_effect=OperationalError(
            "SELECT 1",
            {},
            OSError("postgresql://secret-user:secret-password@db/internal"),
        )
    )
    app = create_app(settings, database=database)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/ready")

    payload = response.json()
    assert response.status_code == 503
    assert payload["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert payload["retryable"] is True
    assert "secret-password" not in response.text
    await database.dispose()
