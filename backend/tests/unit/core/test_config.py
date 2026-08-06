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
        export_signing_secret="test-export-signing-secret",
        demo_merchant_tokens={"demo-token": UUID("00000000-0000-0000-0000-000000000001")},
        demo_merchants_endpoint_enabled=True,
    )

    assert settings.demo_merchants_endpoint_enabled is False


def test_production_requires_export_signing_secret() -> None:
    with pytest.raises(ValidationError, match="EXPORT_SIGNING_SECRET"):
        make_settings(app_env=AppEnvironment.PRODUCTION)


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


def test_max_llm_env_keys_from_the_plan_actually_bind() -> None:
    settings = Settings.model_validate(
        {
            "database_url": "postgresql+psycopg://user:pass@localhost/db",
            "frontend_origin": "https://merchant.example.com",
            "MAX_LLM_CALLS_PER_REQUEST": 7,
            "MAX_LLM_TOKENS_PER_REQUEST": 1234,
        }
    )

    assert settings.llm_max_calls_per_request == 7
    assert settings.llm_max_tokens_per_request == 1234


def test_settings_can_still_be_built_by_field_name() -> None:
    settings = make_settings(llm_max_tokens_per_request=1234)

    assert settings.llm_max_tokens_per_request == 1234


def test_production_with_real_llm_key_requires_admin_token() -> None:
    with pytest.raises(ValidationError, match="ADMIN_TOKEN"):
        make_settings(
            app_env=AppEnvironment.PRODUCTION,
            llm_api_key="real-deepseek-key",
            export_signing_secret="a-secure-export-signing-secret",
        )


@pytest.mark.parametrize("secret", ["short", "<development-placeholder>"])
def test_production_rejects_weak_placeholder_secrets(secret: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(
            app_env=AppEnvironment.PRODUCTION,
            llm_api_key="real-deepseek-key",
            admin_token=secret,
            export_signing_secret=secret,
        )


def test_trusted_proxy_ips_parses_comma_separated_env_value() -> None:
    settings = make_settings(trusted_proxy_ips=" 203.0.113.7, 198.51.100.9 ,, ")

    assert settings.trusted_proxy_ip_set == frozenset({"203.0.113.7", "198.51.100.9"})
