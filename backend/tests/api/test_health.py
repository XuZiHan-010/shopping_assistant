import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_is_lightweight_and_returns_version(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


@pytest.mark.asyncio
async def test_health_propagates_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-Id": "health-check-123"})

    assert response.headers["X-Request-Id"] == "health-check-123"
