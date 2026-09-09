"""Create the merchant-isolated machine translation cache and resource localizations.

Revision ID: 20260831_0015
Revises: 20260823_0014

`machine_translation_cache` 是省 token 的 LLM 译文旁路缓存，按「作用域 + 源哈希 +
源语言 + 目标语言 + prompt_version」去重，默认 30 天过期。`resource_localizations`
只保存人工确认版本，按「作用域 + 资源类型 + 资源 ID + 字段名 + 目标语言」唯一，
不按纯文本哈希跨资源复用，并额外记录 `source_hash`/`source_version` 供调用方判断
译文是否仍对应当前源内容。

两表都用 CHECK 约束强制 `MERCHANT` 作用域必须携带 `merchant_id`、`GLOBAL` 必须为
空；再各拆成两条按 `scope_kind` 过滤的表达式唯一索引，避免 PostgreSQL 唯一索引里
`NULL` 互不相等导致 `GLOBAL` 行可以对同一逻辑键无限重复插入。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0015"
down_revision: str | Sequence[str] | None = "20260823_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_KIND_CHECK = "scope_kind IN ('MERCHANT', 'GLOBAL')"
_SCOPE_MERCHANT_CHECK = (
    "(scope_kind = 'MERCHANT' AND merchant_id IS NOT NULL) "
    "OR (scope_kind = 'GLOBAL' AND merchant_id IS NULL)"
)
_SOURCE_LANGUAGE_CHECK = "source_language IN ('zh-CN', 'en-US', 'mixed', 'und')"
_TARGET_LOCALE_CHECK = "target_locale IN ('zh-CN', 'en-US')"


def upgrade() -> None:
    op.create_table(
        "machine_translation_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_language", sa.String(length=16), nullable=False),
        sa.Column("target_locale", sa.String(length=16), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column(
            "prompt_version", sa.String(length=32), server_default=sa.text("'v1'"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_accessed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now() + interval '30 days'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_SCOPE_KIND_CHECK, name="ck_machine_translation_cache_scope_kind"),
        sa.CheckConstraint(
            _SCOPE_MERCHANT_CHECK, name="ck_machine_translation_cache_scope_merchant"
        ),
        sa.CheckConstraint(
            _SOURCE_LANGUAGE_CHECK, name="ck_machine_translation_cache_source_language"
        ),
        sa.CheckConstraint(_TARGET_LOCALE_CHECK, name="ck_machine_translation_cache_target_locale"),
    )
    op.create_index(
        "uq_machine_translation_cache_global",
        "machine_translation_cache",
        ["source_hash", "source_language", "target_locale", "prompt_version"],
        unique=True,
        postgresql_where=sa.text("scope_kind = 'GLOBAL'"),
    )
    op.create_index(
        "uq_machine_translation_cache_merchant",
        "machine_translation_cache",
        ["merchant_id", "source_hash", "source_language", "target_locale", "prompt_version"],
        unique=True,
        postgresql_where=sa.text("scope_kind = 'MERCHANT'"),
    )
    op.create_index(
        "ix_machine_translation_cache_expires_at",
        "machine_translation_cache",
        ["expires_at"],
    )

    op.create_table(
        "resource_localizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(length=32), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("source_language", sa.String(length=16), nullable=False),
        sa.Column("target_locale", sa.String(length=16), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # `resource_id` 多态引用知识文档/商家记忆等不同表，不建数据库外键；
        # 删除对应资源时由调用方 Service 在同一事务显式清理本表（见
        # `LocalizationRepository.delete_resource_localizations()`），并由
        # 集成测试锁定这一行为。
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_SCOPE_KIND_CHECK, name="ck_resource_localizations_scope_kind"),
        sa.CheckConstraint(_SCOPE_MERCHANT_CHECK, name="ck_resource_localizations_scope_merchant"),
        sa.CheckConstraint(
            _SOURCE_LANGUAGE_CHECK, name="ck_resource_localizations_source_language"
        ),
        sa.CheckConstraint(_TARGET_LOCALE_CHECK, name="ck_resource_localizations_target_locale"),
    )
    op.create_index(
        "uq_resource_localizations_global",
        "resource_localizations",
        ["resource_type", "resource_id", "field_name", "target_locale"],
        unique=True,
        postgresql_where=sa.text("scope_kind = 'GLOBAL'"),
    )
    op.create_index(
        "uq_resource_localizations_merchant",
        "resource_localizations",
        ["merchant_id", "resource_type", "resource_id", "field_name", "target_locale"],
        unique=True,
        postgresql_where=sa.text("scope_kind = 'MERCHANT'"),
    )
    op.create_index(
        "ix_resource_localizations_resource",
        "resource_localizations",
        ["resource_type", "resource_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_resource_localizations_resource", table_name="resource_localizations")
    op.drop_index("uq_resource_localizations_merchant", table_name="resource_localizations")
    op.drop_index("uq_resource_localizations_global", table_name="resource_localizations")
    op.drop_table("resource_localizations")

    op.drop_index(
        "ix_machine_translation_cache_expires_at", table_name="machine_translation_cache"
    )
    op.drop_index("uq_machine_translation_cache_merchant", table_name="machine_translation_cache")
    op.drop_index("uq_machine_translation_cache_global", table_name="machine_translation_cache")
    op.drop_table("machine_translation_cache")
