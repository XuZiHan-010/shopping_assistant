from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.errors import DatabaseUnavailableError
from app.db.session import Database


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://user:pass@localhost/test",
        "frontend_origin": "http://localhost:5173",
        "db_connect_max_attempts": 2,
        "db_connect_retry_seconds": 0.01,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_connect_with_retry_stops_after_configured_attempts() -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    database = Database(make_settings(), sleep=record_sleep)
    database.ping = AsyncMock(  # type: ignore[method-assign]
        side_effect=OperationalError("SELECT 1", {}, OSError("database unavailable"))
    )

    with pytest.raises(DatabaseUnavailableError):
        await database.connect_with_retry()

    assert database.ping.await_count == 2
    assert delays == [0.01]
    await database.dispose()


@pytest.mark.asyncio
async def test_connect_with_retry_returns_after_first_success() -> None:
    database = Database(make_settings())
    database.ping = AsyncMock(return_value=None)  # type: ignore[method-assign]

    await database.connect_with_retry()

    database.ping.assert_awaited_once()
    await database.dispose()
