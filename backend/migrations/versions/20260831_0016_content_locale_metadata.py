"""Add content-language metadata to messages, answers, knowledge, memories, merchants and llm_usage.

Revision ID: 20260831_0016
Revises: 20260831_0015

新增五个内容语言分类列（`messages.source_locale`、`answers.response_locale`、
`knowledge_documents.source_locale`、`merchant_memories.source_locale`）加一个人工
维护列（`merchants.display_name_en`），并给 `llm_usage` 加一个调用用途列
（`purpose`）。

四个分类列**禁止用数据库默认值把历史行一律标成 `zh-CN`**——这会把英文/混合内容
的商家历史数据永久误标。做法是在本迁移内冻结一份不依赖运行时代码
（`app.localization.locales`）的确定性分类函数，对每张表的历史行先用它逐行分类
回填，再收紧为 `NOT NULL` 并加 CHECK 约束。之所以不直接 `import
app.localization.locales`：迁移文件一旦执行就永久锁定，若未来运行时函数的分类
逻辑变化，再次运行本迁移（例如降级重跑）会用新逻辑覆盖旧历史数据，产生和当初
真实回填不一致的结果。这里的实现在编写时与
`app/localization/locales.py::detect_source_language()` 逐字同步；后续如果运行时
分类逻辑变化，不需要、也不应该回来改这个文件。

`llm_usage.purpose` 不属于内容语言分类——历史行全部是 Chat Agent 调用，`AGENT`
默认值本身就是分类结果（不存在别的可能取值），因此直接用 `server_default`
回填，不需要逐行分类。`merchants.display_name_en` 是全新的人工维护字段，同样不
存在历史值可回填，允许为空。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0016"
down_revision: str | Sequence[str] | None = "20260831_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCALE_CHECK = "IN ('zh-CN', 'en-US', 'mixed', 'und')"

# ---------------------------------------------------------------------------
# 冻结副本：与 app/localization/locales.py::detect_source_language() 及其内部
# 辅助正则在编写本迁移时逐字一致。迁移执行后永久锁定，不随运行时函数演进而
# 改变——见模块顶部说明。
# ---------------------------------------------------------------------------

_URL_PATTERN = re.compile(r"https?://\S+")
_CODE_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER_PATTERN = re.compile(r"\d+")
_HAN_PATTERN = re.compile("[一-鿿]")
_LATIN_WORD_PATTERN = re.compile(r"[A-Za-z]{2,}")

_SQL_SELECT_PATTERN = re.compile(
    r"(?i)\bselect\b.*?\bfrom\b\s+[A-Za-z_][\w.]*(?:\s+where\b[^\n;]*)?"
)

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
    "SUM",
    "COUNT",
    "AVG",
    "MAX",
    "MIN",
    "AS",
    "AND",
    "OR",
}


def _replace_code_token(match: re.Match[str]) -> str:
    token = match.group(0)
    if "_" in token or any(ch.isdigit() for ch in token):
        return " "
    if token.upper() in _SQL_KEYWORDS:
        return " "
    return token


def _strip_non_linguistic(text_value: str) -> str:
    stripped = _URL_PATTERN.sub(" ", text_value)
    stripped = _SQL_SELECT_PATTERN.sub(" ", stripped)
    stripped = _CODE_TOKEN_PATTERN.sub(_replace_code_token, stripped)
    stripped = _NUMBER_PATTERN.sub(" ", stripped)
    return stripped


def _detect_source_language(text_value: str) -> str:
    """`SourceLanguage` 的字符串取值（`zh-CN`/`en-US`/`mixed`/`und`），冻结副本。"""

    cleaned = _strip_non_linguistic(text_value or "")
    has_han = bool(_HAN_PATTERN.search(cleaned))
    has_english_word = bool(_LATIN_WORD_PATTERN.search(cleaned))

    if has_han and has_english_word:
        return "mixed"
    if has_han:
        return "zh-CN"
    if has_english_word:
        return "en-US"
    return "und"


def _backfill_locale_column(
    connection: sa.engine.Connection,
    *,
    table: str,
    text_columns: list[str],
    target_column: str,
) -> None:
    """按 `text_columns` 拼接文本逐行分类，写回 `target_column`。"""

    columns_sql = ", ".join(text_columns)
    rows = connection.execute(sa.text(f"SELECT id, {columns_sql} FROM {table}")).mappings().all()

    updates: list[dict[str, Any]] = []
    for row in rows:
        combined = "\n".join(str(row[column]) for column in text_columns if row[column] is not None)
        updates.append({"id": row["id"], "locale": _detect_source_language(combined)})

    if not updates:
        return

    connection.execute(
        sa.text(f"UPDATE {table} SET {target_column} = :locale WHERE id = :id"),
        updates,
    )


def _backfill_answers_response_locale(connection: sa.engine.Connection) -> None:
    """回答按 `response_payload` 中的人类可读字段（顶层 `answer`）分类；
    `response_payload` 为空（尚未成功生成、或失败请求）、或其中没有 `answer`
    键时按空字符串处理，分类结果是 `und`。用 `->>` 让 PostgreSQL 直接把该
    键抽成文本返回，不依赖 DBAPI 对 JSONB 的隐式反序列化行为。"""

    rows = connection.execute(
        sa.text("SELECT id, response_payload ->> 'answer' AS answer_text FROM answers")
    ).mappings().all()

    updates: list[dict[str, Any]] = [
        {"id": row["id"], "locale": _detect_source_language(row["answer_text"] or "")}
        for row in rows
    ]

    if not updates:
        return

    connection.execute(
        sa.text("UPDATE answers SET response_locale = :locale WHERE id = :id"),
        updates,
    )


def upgrade() -> None:
    connection = op.get_bind()
    # `alembic upgrade --sql` 只生成脱机 SQL 脚本，没有真实连接可供 Python 侧
    # 逐行分类读取——`op.get_bind()` 在该模式下返回的是不执行任何查询的
    # `MockConnection`。脱机模式因此只负责渲染下面的 DDL（加列、加约束），跳过
    # 需要读数据的分类回填；真正的历史数据回填必须走在线模式
    # （`alembic upgrade head`）才会执行。
    offline = op.get_context().as_sql

    # -- messages.source_locale --------------------------------------------------
    op.add_column("messages", sa.Column("source_locale", sa.String(length=16), nullable=True))
    if not offline:
        _backfill_locale_column(
            connection, table="messages", text_columns=["content"], target_column="source_locale"
        )
    op.alter_column("messages", "source_locale", nullable=False)
    op.create_check_constraint(
        "ck_messages_source_locale", "messages", f"source_locale {_LOCALE_CHECK}"
    )

    # -- answers.response_locale --------------------------------------------------
    op.add_column("answers", sa.Column("response_locale", sa.String(length=16), nullable=True))
    if not offline:
        _backfill_answers_response_locale(connection)
    op.alter_column("answers", "response_locale", nullable=False)
    op.create_check_constraint(
        "ck_answers_response_locale", "answers", f"response_locale {_LOCALE_CHECK}"
    )

    # -- knowledge_documents.source_locale ----------------------------------------
    op.add_column(
        "knowledge_documents", sa.Column("source_locale", sa.String(length=16), nullable=True)
    )
    if not offline:
        _backfill_locale_column(
            connection,
            table="knowledge_documents",
            text_columns=["title", "content"],
            target_column="source_locale",
        )
    op.alter_column("knowledge_documents", "source_locale", nullable=False)
    op.create_check_constraint(
        "ck_knowledge_documents_source_locale",
        "knowledge_documents",
        f"source_locale {_LOCALE_CHECK}",
    )

    # -- merchant_memories.source_locale -------------------------------------------
    op.add_column(
        "merchant_memories", sa.Column("source_locale", sa.String(length=16), nullable=True)
    )
    if not offline:
        _backfill_locale_column(
            connection,
            table="merchant_memories",
            text_columns=["content"],
            target_column="source_locale",
        )
    op.alter_column("merchant_memories", "source_locale", nullable=False)
    op.create_check_constraint(
        "ck_merchant_memories_source_locale",
        "merchant_memories",
        f"source_locale {_LOCALE_CHECK}",
    )

    # -- merchants.display_name_en：全新人工字段，无历史值可回填，允许为空 ----------
    op.add_column("merchants", sa.Column("display_name_en", sa.String(length=120), nullable=True))

    # -- llm_usage.purpose：历史行全部是 Agent 调用，不是语言分类，直接用默认值 ------
    op.add_column(
        "llm_usage",
        sa.Column(
            "purpose",
            sa.String(length=16),
            server_default=sa.text("'AGENT'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_llm_usage_purpose", "llm_usage", "purpose IN ('AGENT', 'LOCALIZATION')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_usage_purpose", "llm_usage", type_="check")
    op.drop_column("llm_usage", "purpose")

    op.drop_column("merchants", "display_name_en")

    op.drop_constraint("ck_merchant_memories_source_locale", "merchant_memories", type_="check")
    op.drop_column("merchant_memories", "source_locale")

    op.drop_constraint("ck_knowledge_documents_source_locale", "knowledge_documents", type_="check")
    op.drop_column("knowledge_documents", "source_locale")

    op.drop_constraint("ck_answers_response_locale", "answers", type_="check")
    op.drop_column("answers", "response_locale")

    op.drop_constraint("ck_messages_source_locale", "messages", type_="check")
    op.drop_column("messages", "source_locale")
