from uuid import UUID

import pytest

from app.core.config import Settings
from app.core.errors import AuthRequiredError
from app.core.security import resolve_demo_token

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-000000000001")


def settings_with_token() -> Settings:
    return Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        demo_merchant_tokens={"merchant-one-token": MERCHANT_ONE_ID},
    )


def test_valid_demo_token_resolves_trusted_merchant() -> None:
    context = resolve_demo_token("merchant-one-token", settings_with_token())

    assert context.merchant_id == MERCHANT_ONE_ID
    assert context.is_admin is False


def test_invalid_demo_token_is_rejected() -> None:
    with pytest.raises(AuthRequiredError):
        resolve_demo_token("forged-token", settings_with_token())
