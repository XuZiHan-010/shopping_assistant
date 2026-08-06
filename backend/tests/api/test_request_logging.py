"""main.py 挂载的 app.state.metrics 与请求耗时记录。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import AppEnvironment, Settings
from app.main import create_app


def _settings() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        rate_limit_per_minute=1_000,
    )


@pytest.mark.asyncio
async def test_app_state_exposes_operational_metrics() -> None:
    from app.core.metrics import OperationalMetrics

    app = create_app(_settings())

    assert isinstance(app.state.metrics, OperationalMetrics)


@pytest.mark.asyncio
async def test_health_request_records_route_duration() -> None:
    app = create_app(_settings())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert "/api/health" in app.state.metrics.route_average_ms
    assert app.state.metrics.route_average_ms["/api/health"] >= 0
