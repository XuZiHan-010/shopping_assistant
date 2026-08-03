from uuid import UUID

import pytest
from pydantic import ValidationError

from app.core.config import AppEnvironment, Settings


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://user:pass@localhost/db",
        "frontend_origin": "https://merchant.example.com",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_production_disables_demo_merchant_endpoint() -> None:
    settings = make_settings(
        app_env=AppEnvironment.PRODUCTION,
        demo_merchant_tokens={"demo-token": UUID("00000000-0000-0000-0000-000000000001")},
        demo_merchants_endpoint_enabled=True,
    )

    assert settings.demo_merchants_endpoint_enabled is False


def test_cors_origin_must_be_exact() -> None:
    with pytest.raises(ValidationError):
        make_settings(frontend_origin="*")


@pytest.mark.parametrize(
    "origin",
    [
        "https://merchant.example.com/path",
        "https://merchant.example.com?source=test",
        "https://user:pass@merchant.example.com",
    ],
)
def test_cors_origin_rejects_non_origin_url_parts(origin: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(frontend_origin=origin)


def test_railway_postgres_url_uses_psycopg_driver() -> None:
    settings = make_settings(database_url="postgresql://user:pass@localhost/db")

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost/db"


def test_business_timezone_is_fixed() -> None:
    with pytest.raises(ValidationError):
        make_settings(business_timezone="UTC")
