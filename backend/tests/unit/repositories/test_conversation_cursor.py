"""消息分页游标编解码（Task 7，§8.6.3）：不需要数据库,纯函数级验收。

真正的分页行为（第一页取最新 N 条、页内时间正序、`has_more_messages`）
需要真实 PostgreSQL，见 `tests/integration/repositories/test_conversation_repository.py`；
本文件只覆盖游标本身的编解码与作用域校验，这部分逻辑不接触数据库。
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.errors import InvalidRequestError
from app.repositories.conversation import _decode_message_cursor, _encode_message_cursor

MERCHANT_ONE = uuid4()
MERCHANT_TWO = uuid4()
CONVERSATION_ONE = uuid4()
CONVERSATION_TWO = uuid4()
MESSAGE_ID = uuid4()
CREATED_AT = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def _make_cursor() -> str:
    return _encode_message_cursor(
        merchant_id=MERCHANT_ONE,
        conversation_id=CONVERSATION_ONE,
        created_at=CREATED_AT,
        message_id=MESSAGE_ID,
    )


def test_cursor_round_trips_the_encoded_boundary() -> None:
    cursor = _make_cursor()

    created_at, message_id = _decode_message_cursor(
        cursor, merchant_id=MERCHANT_ONE, conversation_id=CONVERSATION_ONE
    )

    assert created_at == CREATED_AT
    assert message_id == MESSAGE_ID


def test_cursor_is_opaque_base64_not_a_readable_boundary_literal() -> None:
    """"不透明"指调用方不能从游标字面值直接读出 UUID/时间戳——这里只断言
    它不是 `created_at`/`message_id` 的明文拼接，不代表游标本身是加密的
    （§8.6.3 用的词是"不透明"，不是"加密"，见 brief Step 4）。"""

    cursor = _make_cursor()

    assert str(MESSAGE_ID) not in cursor
    assert CREATED_AT.isoformat() not in cursor


def test_cursor_rejects_reuse_across_conversations() -> None:
    """同一商家、不同会话复用游标必须产生稳定错误，而不是静默按错误的时间
    边界分页（brief Step 4：「跨商家或跨会话复用返回稳定错误码」）。"""

    cursor = _make_cursor()

    with pytest.raises(InvalidRequestError) as exc_info:
        _decode_message_cursor(
            cursor, merchant_id=MERCHANT_ONE, conversation_id=CONVERSATION_TWO
        )
    assert exc_info.value.code.value == "INVALID_REQUEST"
    assert exc_info.value.status_code == 422


def test_cursor_rejects_reuse_across_merchants() -> None:
    cursor = _make_cursor()

    with pytest.raises(InvalidRequestError):
        _decode_message_cursor(
            cursor, merchant_id=MERCHANT_TWO, conversation_id=CONVERSATION_ONE
        )


def test_cursor_rejects_a_tampered_payload() -> None:
    """修改签名覆盖范围内的任意字段（这里改 `message_id`）而不重算签名，
    必须被检测为签名不匹配，不能被当作"换了个边界"悄悄接受。"""

    cursor = _make_cursor()
    token = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    token["p"]["message_id"] = str(uuid4())
    tampered = base64.urlsafe_b64encode(
        json.dumps(token, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")

    with pytest.raises(InvalidRequestError):
        _decode_message_cursor(
            tampered, merchant_id=MERCHANT_ONE, conversation_id=CONVERSATION_ONE
        )


def test_cursor_rejects_garbage_input() -> None:
    with pytest.raises(InvalidRequestError):
        _decode_message_cursor(
            "not-a-real-cursor", merchant_id=MERCHANT_ONE, conversation_id=CONVERSATION_ONE
        )


def test_cursor_rejects_empty_input() -> None:
    with pytest.raises(InvalidRequestError):
        _decode_message_cursor("", merchant_id=MERCHANT_ONE, conversation_id=CONVERSATION_ONE)
