from __future__ import annotations

from app.core.seed_config import SeedSettings
from app.jobs.seed_demo_rolling import require_demo_refresh_permission


def _settings(**overrides: object) -> SeedSettings:
    values: dict[str, object] = {"database_url": "postgresql+psycopg://user:pass@localhost/demo"}
    values.update(overrides)
    return SeedSettings(**values)


def test_demo_refresh_permission_defaults_to_closed_for_missing_or_invalid_values() -> None:
    assert _settings().allow_demo_data_refresh is False
    assert _settings(allow_demo_data_refresh="yes").allow_demo_data_refresh is False


def test_demo_refresh_permission_requires_explicit_true_before_writing() -> None:
    settings = _settings(allow_demo_data_refresh=True)

    assert settings.allow_demo_data_refresh is True
    require_demo_refresh_permission(settings)
