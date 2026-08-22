"""知识库虚拟路径策略。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

BUSINESS_SECTIONS: Final[tuple[str, ...]] = (
    "业务流程",
    "业务名词解释",
    "ddl",
    "指标或调用指标平台mcp的skill",
)
RESERVED_DOMAIN_NAMES: Final[frozenset[str]] = frozenset({"index", "memory", "业务"})

_MAX_PATH_LENGTH: Final[int] = 512
_MAX_SEGMENT_LENGTH: Final[int] = 120
_ILLEGAL_SEGMENT_CHARS: Final[re.Pattern[str]] = re.compile(r'[:*?"<>|]')


class KnowledgePathError(Exception):
    def __init__(self, code: str, message: str, path: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path
        self.status_code = status_code


@dataclass(frozen=True)
class ResolvedPath:
    virtual_path: str
    read_only: bool


def normalize_virtual_path(raw: str) -> str:
    if not raw or not raw.strip() or raw.startswith("/") or "\\" in raw:
        raise _invalid(raw, "路径格式不合法")
    value = unicodedata.normalize("NFC", raw)
    if len(value) > _MAX_PATH_LENGTH:
        raise _invalid(raw, "路径长度超过限制")

    segments = value.split("/")
    return "/".join(_normalize_segment(segment, raw) for segment in segments)


def resolve_readable(raw: str) -> ResolvedPath:
    path = normalize_virtual_path(raw)
    root = path.split("/", 1)[0]
    if root not in {"index", "业务", "memory"}:
        raise _invalid(path, "路径不在知识库根目录内")
    return ResolvedPath(virtual_path=path, read_only=root == "memory")


def resolve_writable_document(raw: str) -> ResolvedPath:
    path = normalize_virtual_path(raw)
    root = path.split("/", 1)[0]
    if root == "memory":
        raise KnowledgePathError("WIKI_READ_ONLY", "商家记忆只读", path, 403)

    segments = path.split("/")
    is_index_document = len(segments) == 2 and segments[0] == "index"
    is_business_document = (
        len(segments) == 4 and segments[0] == "业务" and segments[2] in BUSINESS_SECTIONS
    )
    if not (is_index_document or is_business_document) or not _is_markdown(segments[-1]):
        raise _invalid(path, "仅允许写入知识库 Markdown 文档")
    return ResolvedPath(virtual_path=path, read_only=False)


def validate_domain_name(raw: str) -> str:
    value = _normalize_segment(raw, raw)
    if value.casefold() in {name.casefold() for name in RESERVED_DOMAIN_NAMES}:
        raise _invalid(raw, "业务域名称为保留字")
    if value in BUSINESS_SECTIONS or value.endswith(".md"):
        raise _invalid(raw, "业务域名称不合法")
    return value


def _is_markdown(filename: str) -> bool:
    return filename.endswith(".md") and len(filename) > len(".md")


def _normalize_segment(segment: str, path: str) -> str:
    if not segment or not segment.strip():
        raise _invalid(path, "路径段不能为空")
    if (
        segment != segment.strip()
        or segment in {".", ".."}
        or segment.startswith(".")
        or len(segment) > _MAX_SEGMENT_LENGTH
        or not all(char.isprintable() for char in segment)
        or _ILLEGAL_SEGMENT_CHARS.search(segment)
    ):
        raise _invalid(path, "路径段格式不合法")
    return segment


def _invalid(path: str, message: str) -> KnowledgePathError:
    return KnowledgePathError("INVALID_WIKI_PATH", message, path)
