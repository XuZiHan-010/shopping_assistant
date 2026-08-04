"""旧 Wiki 的纯解析逻辑，供 CLI 与测试共同使用。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_EXCLUDED_DIRS = ("ddl", "指标或调用指标平台mcp的skill")
_INCOMPLETE_MARKER = "待团队补充"
_BRAND_PATTERN = re.compile(r"yshopping", re.IGNORECASE)
_DOMAIN_BY_DIRECTORY = {
    "交易": "TRADE",
    "退货": "REFUND",
    "客服工单": "CS_TICKET",
    "理赔赔付": "COMPENSATION",
    "优惠券": "COUPON",
    "商品": "GOODS",
    "商家其他": "MERCHANT_OTHER",
    "身份信息": "IDENTITY",
    "供应链": "SCM",
    "平台规则": "PLATFORM_RULE",
}


@dataclass(frozen=True)
class WikiEntry:
    source_path: str
    category: str
    title: str
    content: str
    is_complete: bool


def parse_wiki_tree(root: Path) -> list[WikiEntry]:
    """读取只读参考树，规范化路径、品牌和文档元信息。"""

    entries: list[WikiEntry] = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part in _EXCLUDED_DIRS for part in relative.parts):
            continue
        raw = path.read_text(encoding="utf-8")
        category = next(
            (_DOMAIN_BY_DIRECTORY[part] for part in relative.parts if part in _DOMAIN_BY_DIRECTORY),
            "UNKNOWN",
        )
        entries.append(
            WikiEntry(
                relative.as_posix(),
                category,
                path.stem,
                _BRAND_PATTERN.sub("Borough", raw),
                _INCOMPLETE_MARKER not in raw,
            )
        )
    return entries
