"""请求显示语言与内容源语言识别。

`SupportedLocale` 表达"响应应该用什么语言渲染"，只允许 `zh-CN`/`en-US`
两个值；`SourceLanguage` 表达"这段文本本身是什么语言"，用于给消息、知识
正文等内容打标签，多出 `mixed`/`und` 两个值。两者语义不同，不得混用——
详见 `docs/backend-development-plan.md` §8.6。
"""

from __future__ import annotations

import re
from enum import StrEnum


class SupportedLocale(StrEnum):
    """API 响应可渲染的显示语言。"""

    ZH_CN = "zh-CN"
    EN_US = "en-US"


class SourceLanguage(StrEnum):
    """任意文本内容本身使用的语言标注,用于分类而非渲染。"""

    ZH_CN = "zh-CN"
    EN_US = "en-US"
    MIXED = "mixed"
    UND = "und"


def parse_accept_language(header: str | None) -> SupportedLocale:
    """解析 `Accept-Language`，只认 `zh-CN`/`en-US` 及其通用前缀。

    - Header 缺失、为空或没有可识别取值时回退 `zh-CN`；
    - 支持 `q` 权重（如 `en;q=0.9`），按权重从高到低依次尝试匹配；
    - 不受支持的语言（如 `fr-FR`）被忽略，不影响其余候选的匹配，也不提前
      导致整体解析失败。
    """

    if not header:
        return SupportedLocale.ZH_CN

    candidates: list[tuple[float, str]] = []
    for raw_part in header.split(","):
        part = raw_part.strip()
        if not part:
            continue
        tag, _, param = part.partition(";")
        tag = tag.strip().lower()
        if not tag:
            continue
        quality = 1.0
        param = param.strip()
        if param.startswith("q="):
            try:
                quality = float(param[2:])
            except ValueError:
                quality = 0.0
        candidates.append((quality, tag))

    # 权重高的候选优先尝试；同权重保持 Header 中出现的先后顺序（sort 稳定）。
    candidates.sort(key=lambda item: item[0], reverse=True)

    for _, tag in candidates:
        if tag in ("zh-cn", "zh"):
            return SupportedLocale.ZH_CN
        if tag in ("en-us", "en"):
            return SupportedLocale.EN_US
        if tag.startswith("zh"):
            return SupportedLocale.ZH_CN
        if tag.startswith("en"):
            return SupportedLocale.EN_US

    return SupportedLocale.ZH_CN


_URL_PATTERN = re.compile(r"https?://\S+")
_CODE_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER_PATTERN = re.compile(r"\d+")
_HAN_PATTERN = re.compile("[一-鿿]")
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]{2,}")

# 常见大写 SQL 关键字。只在整个记号全大写且命中表内取值时剔除，避免误伤
# "as"、"in"、"on"、"by"、"not" 这类同时也是普通英文单词的小写用法。
_SQL_KEYWORDS = {
    "SELECT",
    "FROM",
    "WHERE",
    "INSERT",
    "UPDATE",
    "DELETE",
    "JOIN",
    "GROUP",
    "ORDER",
    "INTO",
    "VALUES",
    "LIMIT",
    "INNER",
    "LEFT",
    "RIGHT",
    "OUTER",
    "DISTINCT",
    "HAVING",
    "UNION",
}


def _replace_code_token(match: re.Match[str]) -> str:
    token = match.group(0)
    if "_" in token or any(ch.isdigit() for ch in token):
        return " "
    if token.isupper() and token in _SQL_KEYWORDS:
        return " "
    return token


def _strip_non_linguistic(text: str) -> str:
    """剔除 URL、代码/ID 记号、SQL 关键字与数字，只留自然语言片段。"""

    stripped = _URL_PATTERN.sub(" ", text)
    stripped = _CODE_TOKEN_PATTERN.sub(_replace_code_token, stripped)
    stripped = _NUMBER_PATTERN.sub(" ", stripped)
    return stripped


def detect_source_language(text: str) -> SourceLanguage:
    """判定一段文本本身使用的语言。

    先剔除 URL、下划线或数字构成的代码/ID 记号、常见大写 SQL 关键字，
    再根据剩余自然语言片段分类：

    - 汉字与至少两个字母的英文单词都出现 → `mixed`；
    - 只出现汉字 → `zh-CN`；只出现英文单词 → `en-US`；
    - 都不出现（比如只剩 ID、URL、数字和空白）→ `und`。

    单个字母不构成"英文单词"（避免代码残留的单字母误判为英文）；剔除阶段
    只处理 ASCII 记号，不会误删汉字，因此混合文本里的单个汉字不会被这里
    的清理逻辑吞掉，也不会仅凭它就把整段判成纯中文以外的结果。
    """

    cleaned = _strip_non_linguistic(text)
    has_han = bool(_HAN_PATTERN.search(cleaned))
    has_english_word = bool(_LATIN_WORD_PATTERN.search(cleaned))

    if has_han and has_english_word:
        return SourceLanguage.MIXED
    if has_han:
        return SourceLanguage.ZH_CN
    if has_english_word:
        return SourceLanguage.EN_US
    return SourceLanguage.UND
