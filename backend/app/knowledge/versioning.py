"""知识库乐观锁版本号。

文档版本使用内容的 SHA-256；目录版本将虚拟路径与子节点版本按服务端
确定的顺序拼接后再计算 SHA-256。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def document_version(content: str) -> str:
    """返回 UTF-8 文本内容的 SHA-256 十六进制摘要。"""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def directory_version(virtual_path: str, children: Sequence[tuple[str, str]]) -> str:
    """返回目录及其已排序子节点的聚合版本。"""

    signature = f"directory:{virtual_path}"
    for child_path, child_version in children:
        signature += f"\n{child_path}:{child_version}"
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def parse_if_match(raw: str | None) -> str | None:
    """解析可选的 HTTP ``If-Match`` 值，兼容弱 ETag 与双引号。"""

    if raw is None or not raw.strip():
        return None

    candidate = raw.strip()
    if candidate.startswith("W/"):
        candidate = candidate[2:].strip()
    if len(candidate) >= 2 and candidate.startswith('"') and candidate.endswith('"'):
        candidate = candidate[1:-1]
    return candidate
