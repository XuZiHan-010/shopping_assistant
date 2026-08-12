"""require_admin_token：只认 X-Admin-Token，忽略 Authorization。"""

from __future__ import annotations

import pytest
from fastapi import Request

from app.api.dependencies import require_admin_token
from app.core.config import AppEnvironment, Settings
from app.core.errors import AdminForbiddenError, AdminTokenRequiredError


def _settings(admin_token: str | None) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=admin_token,
    )


def _request(headers: dict[str, str]) -> Request:
    encoded = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request({"type": "http", "headers": encoded, "client": ("testclient", 1234)})


def test_missing_header_raises_401() -> None:
    with pytest.raises(AdminTokenRequiredError):
        require_admin_token(_request({}), _settings("correct-admin-token-value"))


def test_wrong_token_raises_403() -> None:
    with pytest.raises(AdminForbiddenError):
        require_admin_token(
            _request({"X-Admin-Token": "merchant-one-token"}),
            _settings("correct-admin-token-value"),
        )


def test_correct_token_passes() -> None:
    require_admin_token(
        _request({"X-Admin-Token": "correct-admin-token-value"}),
        _settings("correct-admin-token-value"),
    )


def test_authorization_header_is_ignored() -> None:
    with pytest.raises(AdminTokenRequiredError):
        require_admin_token(
            _request({"Authorization": "Bearer correct-admin-token-value"}),
            _settings("correct-admin-token-value"),
        )
