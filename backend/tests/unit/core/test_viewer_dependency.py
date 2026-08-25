"""require_admin_or_viewer_token：只读端点认管理员或只读令牌，任一都放行。"""

from __future__ import annotations

import pytest
from fastapi import Request

from app.api.dependencies import require_admin_or_viewer_token
from app.core.config import AppEnvironment, Settings
from app.core.errors import AdminForbiddenError, AdminTokenRequiredError


def _settings(admin_token: str | None, viewer_token: str | None = None) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=admin_token,
        viewer_token=viewer_token,
    )


def _request(headers: dict[str, str]) -> Request:
    encoded = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return Request({"type": "http", "headers": encoded, "client": ("testclient", 1234)})


def test_admin_token_still_passes() -> None:
    require_admin_or_viewer_token(
        _request({"X-Admin-Token": "correct-admin-token-value"}),
        _settings("correct-admin-token-value", "correct-viewer-token-value"),
    )


def test_viewer_token_passes_read_only_dependency() -> None:
    require_admin_or_viewer_token(
        _request({"X-Admin-Token": "correct-viewer-token-value"}),
        _settings("correct-admin-token-value", "correct-viewer-token-value"),
    )


def test_wrong_token_raises_403() -> None:
    with pytest.raises(AdminForbiddenError):
        require_admin_or_viewer_token(
            _request({"X-Admin-Token": "neither-of-them"}),
            _settings("correct-admin-token-value", "correct-viewer-token-value"),
        )


def test_missing_header_raises_401() -> None:
    with pytest.raises(AdminTokenRequiredError):
        require_admin_or_viewer_token(
            _request({}),
            _settings("correct-admin-token-value", "correct-viewer-token-value"),
        )


def test_viewer_token_rejected_when_not_configured() -> None:
    with pytest.raises(AdminForbiddenError):
        require_admin_or_viewer_token(
            _request({"X-Admin-Token": "whatever-value-here"}),
            _settings("correct-admin-token-value", None),
        )


def test_equal_admin_and_viewer_token_is_rejected_at_config_time() -> None:
    """两把钥匙如果长得一样，「只读」这个边界就不存在了——必须在配置阶段拦下，
    而不是指望调用方记得不要配错。"""

    with pytest.raises(ValueError, match=r"ADMIN_TOKEN.*VIEWER_TOKEN"):
        _settings("same-value-here-16-chars", "same-value-here-16-chars")
