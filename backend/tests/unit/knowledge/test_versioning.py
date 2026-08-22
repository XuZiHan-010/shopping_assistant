"""版本号计算，对应参考实现的 WikiAdminService.digest / version。"""

from __future__ import annotations

import hashlib

from app.knowledge.versioning import directory_version, document_version, parse_if_match


def test_document_version_is_sha256_of_utf8_bytes() -> None:
    assert document_version("内容") == hashlib.sha256("内容".encode()).hexdigest()


def test_directory_version_changes_when_any_child_changes() -> None:
    before = directory_version("业务/交易", [("业务/交易/业务流程", "aaa")])
    after = directory_version("业务/交易", [("业务/交易/业务流程", "bbb")])
    assert before != after


def test_directory_version_is_order_stable() -> None:
    """子节点顺序由服务端固定，同一内容必须给出同一版本。"""

    children = [("a", "1"), ("b", "2")]
    assert directory_version("业务", children) == directory_version("业务", children)


def test_empty_directory_still_has_a_version() -> None:
    assert directory_version("业务/新域", []) != ""


def test_parse_if_match_strips_weak_prefix_and_quotes() -> None:
    assert parse_if_match('W/"abc"') == "abc"
    assert parse_if_match('"abc"') == "abc"
    assert parse_if_match("abc") == "abc"
    assert parse_if_match("  abc  ") == "abc"
    assert parse_if_match(None) is None
    assert parse_if_match("   ") is None
