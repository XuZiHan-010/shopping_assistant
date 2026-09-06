"""请求显示语言与内容源语言识别。

`SupportedLocale` 表达"响应应该用什么语言渲染"，只允许 `zh-CN`/`en-US`
两个值；`SourceLanguage` 表达"这段文本本身是什么语言"，用于给消息、知识
正文等内容打标签，多出 `mixed`/`und` 两个值。两者语义不同，不得混用——
详见 `docs/backend-development-plan.md` §8.6。
"""

from __future__ import annotations

import hashlib
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

# 完整 `select ... from <表名> [where ...]` 子句：整段按 SQL 处理，而不是
# 逐词剔除关键字。逐词剔除治不了 `orders`、`id`、`name` 这类不含下划线/
# 数字的裸表名或列名——它们本身也是常见英文单词的形状，仅凭关键字表拦不
# 住（这正是本函数最初漏判 `SELECT * FROM orders WHERE merchant_id = 1`
# 这类真实 SQL 语句的根因）。非贪婪匹配到第一个 `from`，只吞掉紧跟着的
# 一个表名记号与随后可选的 `where` 子句（到行尾/分号为止），不会把 SQL
# 片段前后真正的自然语言说明一并吞掉。
_SQL_SELECT_PATTERN = re.compile(
    r"(?i)\bselect\b.*?\bfrom\b\s+[A-Za-z_][\w.]*(?:\s+where\b[^\n;]*)?"
)

# 常见 SQL 关键字，作为逐词剔除的兜底：覆盖上面的整句子句正则漏网的场景
# （比如关键字单独出现、或出现在 select/from 结构以外的 SQL 片段里）。
# 大小写不敏感匹配——真实 SQL 里 `select`/`from`/`sum` 等关键字几乎总是
# 全部大写或全部小写，混合大小写的情况极少；不收录 `in`/`on`/`by`/`not`
# 这类同时是常见英文单词、且在这里误剔除代价更高的词。
#
# 全仓库唯一一份"活"的 SQL 关键字表：`app.services.localization_service`
# 的 `_protect()`/`_PROTECT_PATTERN` 直接从这里导入复用，不再各写一份——
# 两份独立维护的拷贝曾经真的漂移过（一份有 `DROP`/`TABLE` 没有
# `AS`/`AND`/`OR`，另一份反过来），本次合并取两者并集，任何一处新增关键字
# 都会同时对两个使用方生效。`migrations/versions/20260831_0016_*.py` 里还有
# 第三份**刻意冻结**的拷贝，用于历史行回填分类，不属于本表的复用范围，也
# 永远不应该被改成 import 这里——见该迁移文件模块顶部的说明。
SQL_KEYWORDS = frozenset(
    {
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
        "DROP",
        "TABLE",
        "SUM",
        "COUNT",
        "AVG",
        "MAX",
        "MIN",
        "AS",
        "AND",
        "OR",
    }
)


def _replace_code_token(match: re.Match[str]) -> str:
    token = match.group(0)
    if "_" in token or any(ch.isdigit() for ch in token):
        return " "
    if token.upper() in SQL_KEYWORDS:
        return " "
    return token


def _strip_non_linguistic(text: str) -> str:
    """剔除 URL、SQL 语句、代码/ID 记号、SQL 关键字与数字，只留自然语言片段。

    顺序很关键：SQL 整句子句必须在逐词的代码/关键字剔除**之前**处理，否则
    `select`/`from` 一旦被逐词步骤先行剔除，子句正则就再也找不到匹配起点，
    裸表名/列名（`orders`、`id`、`name`）就会被当成自然语言英文单词漏判。
    """

    stripped = _URL_PATTERN.sub(" ", text)
    stripped = _SQL_SELECT_PATTERN.sub(" ", stripped)
    stripped = _CODE_TOKEN_PATTERN.sub(_replace_code_token, stripped)
    stripped = _NUMBER_PATTERN.sub(" ", stripped)
    return stripped


def detect_source_language(text: str) -> SourceLanguage:
    """判定一段文本本身使用的语言。

    先剔除 URL、完整的 `select ... from ...` 语句、下划线或数字构成的
    代码/ID 记号、常见 SQL 关键字（大小写不敏感），再根据剩余自然语言
    片段分类：

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


def hash_source_text(text: str) -> str:
    """源文本的确定性哈希，是机器译文缓存键（`source_hash`）的唯一算法。

    从 `app.services.localization_service._hash_text` 提升为公共函数
    （Task 7）：会话删除时清理派生缓存（`delete_machine_by_hashes()`）必须
    用与写入时**完全相同**的算法重新计算源哈希，否则删不中任何行——两处
    各写一份 `sha256` 调用只会让今后改算法时悄悄产生不一致。
    """

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
