"""签名游标（契约 §8.7.4）：不透明、绑定主体与查询形状、24 小时过期。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import InvalidCursorError
from app.services.v2.cursor import CursorCodec, CursorScope

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
SECRET = b"unit-test-cursor-secret"

SCOPE = CursorScope(
    endpoint="merchant.drafts.list",
    role="MERCHANT",
    principal_digest="digest-a",
    merchant_id="m-1",
    resource="DRAFT",
    filters={"state": "STAGED", "kind": None},
    locale="zh-CN",
    limit=20,
)


@pytest.fixture
def codec() -> CursorCodec:
    return CursorCodec(secret=SECRET)


def test_round_trip_returns_the_same_sort_key(codec: CursorCodec) -> None:
    cursor = codec.encode(SCOPE, key=("2026-09-23T08:00:00+00:00", "d-9"), now=NOW)

    assert codec.decode(cursor, SCOPE, now=NOW) == ("2026-09-23T08:00:00+00:00", "d-9")


def test_cursor_is_opaque_and_leaks_no_identifiers(codec: CursorCodec) -> None:
    cursor = codec.encode(SCOPE, key=("2026-09-23T08:00:00+00:00", "d-9"), now=NOW)

    assert "m-1" not in cursor
    assert "digest-a" not in cursor
    assert "d-9" not in cursor


def test_tampered_payload_is_rejected(codec: CursorCodec) -> None:
    cursor = codec.encode(SCOPE, key=("k",), now=NOW)
    payload, _, signature = cursor.partition(".")

    with pytest.raises(InvalidCursorError):
        codec.decode(f"{payload}x.{signature}", SCOPE, now=NOW)


def test_unsigned_base64_is_rejected(codec: CursorCodec) -> None:
    """不接受未签名的 base64：游标必须是服务端签发的。"""

    cursor = codec.encode(SCOPE, key=("k",), now=NOW)
    payload, _, _ = cursor.partition(".")

    with pytest.raises(InvalidCursorError):
        codec.decode(payload, SCOPE, now=NOW)


def test_cursor_from_another_secret_is_rejected(codec: CursorCodec) -> None:
    other = CursorCodec(secret=b"another-secret")
    cursor = other.encode(SCOPE, key=("k",), now=NOW)

    with pytest.raises(InvalidCursorError):
        codec.decode(cursor, SCOPE, now=NOW)


@pytest.mark.parametrize(
    "replacement",
    [
        {"principal_digest": "digest-b"},
        {"merchant_id": "m-2"},
        {"role": "CUSTOMER"},
        {"endpoint": "merchant.inventory.alerts"},
        {"resource": "INVENTORY_ALERT"},
        {"filters": {"state": "APPLIED", "kind": None}},
        {"locale": "en-US"},
        {"limit": 50},
    ],
)
def test_cursor_does_not_cross_binding(codec: CursorCodec, replacement: dict[str, object]) -> None:
    """跨主体、跨资源或跨查询形状复用游标一律拒绝，不返回数据。"""

    cursor = codec.encode(SCOPE, key=("k",), now=NOW)
    other_scope = CursorScope(**{**SCOPE.__dict__, **replacement})  # type: ignore[arg-type]

    with pytest.raises(InvalidCursorError):
        codec.decode(cursor, other_scope, now=NOW)


def test_cursor_expires_after_twenty_four_hours(codec: CursorCodec) -> None:
    cursor = codec.encode(SCOPE, key=("k",), now=NOW)

    assert codec.decode(cursor, SCOPE, now=NOW + timedelta(hours=23, minutes=59)) == ("k",)
    with pytest.raises(InvalidCursorError):
        codec.decode(cursor, SCOPE, now=NOW + timedelta(hours=24, seconds=1))


def test_invalid_cursor_error_is_unretryable_422() -> None:
    """重试同一个游标不会成功，客户端必须回首页（§8.7.4 第 5 条）。"""

    error = InvalidCursorError()

    assert (error.status_code, error.retryable) == (422, False)


@pytest.mark.parametrize("garbage", ["", "not-a-cursor", "a.b", "...", "!!!.???"])
def test_garbage_input_is_rejected_without_crashing(codec: CursorCodec, garbage: str) -> None:
    with pytest.raises(InvalidCursorError):
        codec.decode(garbage, SCOPE, now=NOW)
