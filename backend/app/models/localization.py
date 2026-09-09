"""机器翻译缓存与资源级人工译文 ORM。

见 `docs/backend-development-plan.md` §8.6 与
`plans/2026-08-31-full-stack-bilingual-localization.md` §3.2：机器译文与人工译文不
共用主键语义，分别落两张表，并按 `scope_kind` + `merchant_id` 强制隔离——`MERCHANT`
必须携带 `merchant_id`，`GLOBAL` 必须为空。两条 CHECK 约束加两条按作用域拆分的
表达式唯一索引在数据库层面共同保证这一点（避免 PostgreSQL「`NULL` 在唯一索引中
互不相等」导致 `GLOBAL` 行可以无限重复插入的问题）；应用层 `LocalizationRepository`
不提供绕过作用域选择的便利方法，见 `app/repositories/localization.py`。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    UuidPrimaryKeyMixin,
)

_SCOPE_KIND_CHECK = "scope_kind IN ('MERCHANT', 'GLOBAL')"
_SCOPE_MERCHANT_CHECK = (
    "(scope_kind = 'MERCHANT' AND merchant_id IS NOT NULL) "
    "OR (scope_kind = 'GLOBAL' AND merchant_id IS NULL)"
)
_SOURCE_LANGUAGE_CHECK = "source_language IN ('zh-CN', 'en-US', 'mixed', 'und')"
_TARGET_LOCALE_CHECK = "target_locale IN ('zh-CN', 'en-US')"


class MachineTranslationCache(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """LLM 机器译文缓存，按「作用域 + 源哈希 + 源语言 + 目标语言 + prompt_version」去重。

    默认 30 天过期，由 `LocalizationRepository.purge_expired_machine()` 批量清理；
    只是省 token 的旁路缓存，不代表业务事实，未经人工确认不得当作权威译文使用——
    权威译文走 `ResourceLocalization`。
    """

    __tablename__ = "machine_translation_cache"
    __table_args__ = (
        CheckConstraint(_SCOPE_KIND_CHECK, name="ck_machine_translation_cache_scope_kind"),
        CheckConstraint(
            _SCOPE_MERCHANT_CHECK, name="ck_machine_translation_cache_scope_merchant"
        ),
        CheckConstraint(
            _SOURCE_LANGUAGE_CHECK, name="ck_machine_translation_cache_source_language"
        ),
        CheckConstraint(_TARGET_LOCALE_CHECK, name="ck_machine_translation_cache_target_locale"),
        # GLOBAL 行的 merchant_id 恒为 NULL；PostgreSQL 唯一索引里 NULL 互不相等，
        # 若把 merchant_id 放进同一条唯一索引，多条 GLOBAL 缓存就能对同一
        # (源哈希, 源语言, 目标语言, prompt_version) 无限重复插入。拆成两条按
        # scope_kind 过滤的表达式唯一索引，GLOBAL 分支直接不含 merchant_id 列，
        # 彻底避开这个问题；MERCHANT 分支的 merchant_id 恒非空，用普通多列唯一
        # 语义即可。
        Index(
            "uq_machine_translation_cache_global",
            "source_hash",
            "source_language",
            "target_locale",
            "prompt_version",
            unique=True,
            postgresql_where=text("scope_kind = 'GLOBAL'"),
        ),
        Index(
            "uq_machine_translation_cache_merchant",
            "merchant_id",
            "source_hash",
            "source_language",
            "target_locale",
            "prompt_version",
            unique=True,
            postgresql_where=text("scope_kind = 'MERCHANT'"),
        ),
        Index("ix_machine_translation_cache_expires_at", "expires_at"),
    )

    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    merchant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'v1'")
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now() + interval '30 days'"),
    )


class ResourceLocalization(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    """资源字段级人工确认译文，只保存人工确认版本，不按纯文本哈希跨资源复用。

    `resource_id` 是多态引用（知识文档、商家记忆等），不建数据库外键——删除对应
    资源时由调用方 Service 在同一事务里显式调用 `delete_resource_localizations()`
    清理，并由集成测试锁定这一行为。`source_hash`/`source_version` 快照写入时刻
    的源内容指纹；读取时与当前源资源比对，不一致即视为 `STALE`，由
    `LocalizationRepository.get_current_resource_translation()` 判定，本表自身
    不做业务判断。
    """

    __tablename__ = "resource_localizations"
    __table_args__ = (
        CheckConstraint(_SCOPE_KIND_CHECK, name="ck_resource_localizations_scope_kind"),
        CheckConstraint(_SCOPE_MERCHANT_CHECK, name="ck_resource_localizations_scope_merchant"),
        CheckConstraint(_SOURCE_LANGUAGE_CHECK, name="ck_resource_localizations_source_language"),
        CheckConstraint(_TARGET_LOCALE_CHECK, name="ck_resource_localizations_target_locale"),
        Index(
            "uq_resource_localizations_global",
            "resource_type",
            "resource_id",
            "field_name",
            "target_locale",
            unique=True,
            postgresql_where=text("scope_kind = 'GLOBAL'"),
        ),
        Index(
            "uq_resource_localizations_merchant",
            "merchant_id",
            "resource_type",
            "resource_id",
            "field_name",
            "target_locale",
            unique=True,
            postgresql_where=text("scope_kind = 'MERCHANT'"),
        ),
        Index("ix_resource_localizations_resource", "resource_type", "resource_id"),
    )

    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    merchant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=True,
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    field_name: Mapped[str] = mapped_column(String(32), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_locale: Mapped[str] = mapped_column(String(16), nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
