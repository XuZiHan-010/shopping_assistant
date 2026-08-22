"""知识库虚拟路径策略，逐条复刻参考 `WikiPathPolicy`。"""

from __future__ import annotations

import unicodedata

import pytest

from app.knowledge.path_policy import (
    BUSINESS_SECTIONS,
    KnowledgePathError,
    normalize_virtual_path,
    resolve_readable,
    resolve_writable_document,
    validate_domain_name,
)


def test_business_sections_match_reference_verbatim_and_in_order() -> None:
    assert BUSINESS_SECTIONS == (
        "业务流程",
        "业务名词解释",
        "ddl",
        "指标或调用指标平台mcp的skill",
    )


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "/index/a.md",
        "index\\a.md",
        "../secret.md",
        "index/../../etc/passwd",
        "index/./a.md",
        "index/.hidden.md",
        "index/a\x00.md",
        "index/a\nb.md",
        "index/a:b.md",
        'index/a"b.md',
        "index/a|b.md",
        "index/ a.md",
        "x" * 513,
    ],
)
def test_malformed_paths_are_rejected(raw: str) -> None:
    with pytest.raises(KnowledgePathError) as excinfo:
        normalize_virtual_path(raw)
    assert excinfo.value.status_code == 400


def test_nfc_normalization_is_applied() -> None:
    decomposed = "index/你好\u0301.md"
    assert normalize_virtual_path(decomposed) == normalize_virtual_path(
        unicodedata.normalize("NFC", decomposed)
    )


def test_readable_roots_and_memory_read_only() -> None:
    assert resolve_readable("index").read_only is False
    assert resolve_readable("业务/交易").read_only is False
    assert resolve_readable("memory").read_only is True
    assert resolve_readable("memory/merchants/abc/TRADE.md").read_only is True
    with pytest.raises(KnowledgePathError) as excinfo:
        resolve_readable("secrets/a.md")
    assert excinfo.value.code == "INVALID_WIKI_PATH"


def test_memory_is_never_writable() -> None:
    with pytest.raises(KnowledgePathError) as excinfo:
        resolve_writable_document("memory/merchants/abc/TRADE.md")
    assert excinfo.value.code == "WIKI_READ_ONLY"
    assert excinfo.value.status_code == 403


def test_writable_accepts_only_index_or_four_level_business_document() -> None:
    assert resolve_writable_document("index/目录.md").virtual_path == "index/目录.md"
    assert (
        resolve_writable_document("业务/交易/业务流程/下单.md").virtual_path
        == "业务/交易/业务流程/下单.md"
    )
    for invalid in (
        "index/子目录/a.md",
        "业务/交易/下单.md",
        "业务/交易/不存在板块/a.md",
        "业务/交易/业务流程/深层/a.md",
        "业务/交易/业务流程/a.txt",
        "业务/交易/业务流程/.md",
    ):
        with pytest.raises(KnowledgePathError):
            resolve_writable_document(invalid)


@pytest.mark.parametrize("name", ["index", "memory", "业务", "INDEX", "业务流程", "a.md"])
def test_reserved_domain_names_are_rejected(name: str) -> None:
    with pytest.raises(KnowledgePathError):
        validate_domain_name(name)


def test_valid_domain_name_is_normalized() -> None:
    assert validate_domain_name("交易") == "交易"
