"""日志凭证脱敏（`plans/2026-09-21-n1-session-identity.md` Task 4 / Astra D6）。"""

from __future__ import annotations

import logging

import pytest

from app.core.config import Settings
from app.core.logging import REDACTED, configure_logging, redact_sensitive_values
from tests.support.log_capture import reenable_app_logger

SESSION_TOKEN = "sess-plaintext-0123456789abcdefghijklmnopqrstuvwxyz"


@pytest.mark.parametrize(
    "key", ["X-Session-Id", "x-session-id", "x_session_id", "Authorization", "X-Admin-Token"]
)
def test_top_level_credential_keys_are_redacted(key: str) -> None:
    event = redact_sensitive_values(None, "info", {"event": "e", key: SESSION_TOKEN})

    assert event[key] == REDACTED


def test_nested_header_mappings_and_pairs_are_redacted() -> None:
    event = redact_sensitive_values(
        None,
        "info",
        {
            "event": "e",
            "headers": {"X-Session-Id": SESSION_TOKEN, "Accept": "application/json"},
            "raw_headers": [(b"x-session-id", SESSION_TOKEN.encode()), (b"accept", b"*/*")],
            "context": {"request": {"authorization": f"Bearer {SESSION_TOKEN}"}},
        },
    )

    assert event["headers"] == {"X-Session-Id": REDACTED, "Accept": "application/json"}
    assert event["raw_headers"] == [(b"x-session-id", REDACTED), (b"accept", b"*/*")]
    assert event["context"] == {"request": {"authorization": REDACTED}}


def test_v1_conversation_session_id_is_not_a_credential() -> None:
    """v1 `session_id` 是对话 ID，排障需要，不能被误脱敏。"""

    event = redact_sensitive_values(None, "info", {"event": "e", "session_id": "conv-1"})

    assert event["session_id"] == "conv-1"


def test_configured_logger_never_renders_plaintext_session_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = configure_logging(
        Settings(
            database_url="postgresql+psycopg://user:pass@localhost/db",
            frontend_origin="https://merchant.example.com",  # type: ignore[arg-type]
            buyer_alias_secret="test-buyer-alias-secret",
        )
    )
    reenable_app_logger()
    caplog.set_level(logging.INFO)

    logger.info("probe_event", headers={"X-Session-Id": SESSION_TOKEN}, x_session_id=SESSION_TOKEN)

    assert "probe_event" in caplog.text
    assert SESSION_TOKEN not in caplog.text
    assert REDACTED in caplog.text
