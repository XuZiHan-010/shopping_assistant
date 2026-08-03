import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_unknown_route_uses_safe_error_contract(client: AsyncClient) -> None:
    response = await client.get("/api/not-found")

    payload = response.json()
    assert response.status_code == 404
    assert payload["code"] == "NOT_FOUND"
    assert payload["message"] == "请求的资源不存在"
    assert payload["request_id"]
    assert payload["details"] == []
    assert payload["retryable"] is False


@pytest.mark.asyncio
async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-Id": "invalid request id"})

    request_id = response.headers["X-Request-Id"]
    assert request_id != "invalid request id"
    assert len(request_id) == 36
