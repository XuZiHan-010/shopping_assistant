from typing import Annotated
from uuid import UUID

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_merchant_context
from app.core.config import Settings
from app.core.security import MerchantContext
from app.main import create_app

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000001")


def auth_settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        demo_merchant_tokens={"merchant-one-token": MERCHANT_ONE_ID},
    )


@pytest.mark.asyncio
async def test_missing_bearer_token_returns_auth_required() -> None:
    app = create_app(auth_settings())

    @app.get("/test/protected")
    async def protected(
        context: Annotated[MerchantContext, Depends(get_merchant_context)],
    ) -> dict[str, str]:
        return {"merchant_id": str(context.merchant_id)}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/test/protected")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
    await app.state.database.dispose()


@pytest.mark.asyncio
async def test_body_cannot_override_token_merchant() -> None:
    app = create_app(auth_settings())

    @app.post("/test/protected")
    async def protected(
        body: dict[str, str],
        context: Annotated[MerchantContext, Depends(get_merchant_context)],
    ) -> dict[str, str]:
        del body
        return {"merchant_id": str(context.merchant_id)}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/test/protected",
            headers={"Authorization": "Bearer merchant-one-token"},
            json={"merchant_id": "00000000-0000-0000-0000-000000000002"},
        )

    assert response.status_code == 200
    assert response.json() == {"merchant_id": str(MERCHANT_ONE_ID)}
    await app.state.database.dispose()
