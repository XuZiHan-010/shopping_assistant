from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_merchant_repository
from app.core.config import Settings
from app.main import create_app
from app.repositories.merchant import MerchantSummary

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000001")


class FakeMerchantRepository:
    async def list_demo_by_ids(self, merchant_ids: list[UUID]) -> list[MerchantSummary]:
        if MERCHANT_ONE_ID not in merchant_ids:
            return []
        return [
            MerchantSummary(
                merchant_id=MERCHANT_ONE_ID,
                display_name="Borough商家100",
            )
        ]


def demo_settings(*, enabled: bool) -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        demo_merchant_tokens={"merchant-one-token": MERCHANT_ONE_ID},
        demo_merchants_endpoint_enabled=enabled,
    )


@pytest.mark.asyncio
async def test_demo_endpoint_returns_only_server_configured_merchants() -> None:
    app = create_app(demo_settings(enabled=True))
    app.dependency_overrides[get_merchant_repository] = FakeMerchantRepository

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/demo/merchants")

    assert response.status_code == 200
    assert response.json() == {
        "merchants": [
            {
                "merchant_id": str(MERCHANT_ONE_ID),
                "display_name": "Borough商家100",
                "token": "merchant-one-token",
            }
        ]
    }
    await app.state.database.dispose()


@pytest.mark.asyncio
async def test_demo_endpoint_is_hidden_when_disabled() -> None:
    app = create_app(demo_settings(enabled=False))
    app.dependency_overrides[get_merchant_repository] = FakeMerchantRepository

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/demo/merchants")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    await app.state.database.dispose()
