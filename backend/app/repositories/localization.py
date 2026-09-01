"""本地化仓储：机器译文缓存 + 资源级人工译文，纯数据访问，不调用 LLM。

强制作用域接口——不提供「不传 merchant_id 就查全部」的便利方法：全局机器缓存
只能调用 `get_global_machine_many()`，商家机器缓存只能调用
`get_merchant_machine_many(merchant_id=...)`；两者都不接受 `merchant_id: UUID |
None` 这种会让调用方"忘记选作用域"的联合签名。`LocalizationScope` 用于其余
按作用域派发的接口（`get_current_resource_translation()`、`upsert_human()`、
`delete_machine_by_hashes()`），并在应用层复核一次 `MERCHANT` 必须带
`merchant_id`、`GLOBAL` 必须不带——这是数据库 CHECK 约束之外的第二道防线，不
替代它。

业务决策（何时调用 LLM、何时判定需要重译、预算控制）属于 Task 4 的
`LocalizationService`，本仓储只做增删查改。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.localization.locales import SourceLanguage, SupportedLocale
from app.models.localization import MachineTranslationCache, ResourceLocalization

ScopeKind = Literal["MERCHANT", "GLOBAL"]


@dataclass(frozen=True)
class LocalizationScope:
    """`MERCHANT` 必须携带 `merchant_id`；`GLOBAL` 必须为空——由
    `LocalizationRepository._validate_scope()` 与数据库 CHECK 双重强制。"""

    kind: ScopeKind
    merchant_id: UUID | None = None


@dataclass(frozen=True)
class ResourceLocalizationKey:
    """定位一份可本地化资源字段；不含 `merchant_id`/`target_locale`——它们由
    `LocalizationScope` 和方法自身的 `target_locale` 参数分别提供，保持与
    `plans/2026-08-31-full-stack-bilingual-localization.md` §3.2 的
    `ResourceLocalizationKey` 同名同形，供 Task 4 直接复用。"""

    resource_type: Literal["KNOWLEDGE_DOCUMENT", "MERCHANT_MEMORY"]
    resource_id: UUID
    field_name: Literal["title", "content"]


class ResourceLocalizationStatus(StrEnum):
    """`get_current_resource_translation()` 的结果分类。"""

    MISSING = "MISSING"
    CURRENT = "CURRENT"
    STALE = "STALE"


@dataclass(frozen=True)
class ResourceTranslationLookup:
    status: ResourceLocalizationStatus
    record: ResourceLocalization | None


def _validate_scope(scope: LocalizationScope) -> None:
    if scope.kind == "MERCHANT" and scope.merchant_id is None:
        raise ValueError("MERCHANT 作用域必须提供 merchant_id")
    if scope.kind == "GLOBAL" and scope.merchant_id is not None:
        raise ValueError("GLOBAL 作用域不得携带 merchant_id")


class LocalizationRepository:
    """机器译文缓存与资源级人工译文的商家隔离读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # 机器译文缓存
    # ------------------------------------------------------------------

    async def get_merchant_machine_many(
        self,
        *,
        merchant_id: UUID,
        source_hashes: Sequence[str],
        target_locale: SupportedLocale,
        prompt_version: str,
    ) -> dict[str, MachineTranslationCache]:
        """只查该商家自己、且产自 `prompt_version` 这一版翻译提示词的机器缓存，
        绝不返回其它商家、GLOBAL 或其它 `prompt_version` 的行。"""

        return await self._fetch_machine_many(
            scope_kind="MERCHANT",
            merchant_id=merchant_id,
            source_hashes=source_hashes,
            target_locale=target_locale,
            prompt_version=prompt_version,
        )

    async def get_global_machine_many(
        self,
        *,
        source_hashes: Sequence[str],
        target_locale: SupportedLocale,
        prompt_version: str,
    ) -> dict[str, MachineTranslationCache]:
        """只查不含商家归属、且产自 `prompt_version` 这一版翻译提示词的全局机器
        缓存（如平台规则类文案）。"""

        return await self._fetch_machine_many(
            scope_kind="GLOBAL",
            merchant_id=None,
            source_hashes=source_hashes,
            target_locale=target_locale,
            prompt_version=prompt_version,
        )

    async def _fetch_machine_many(
        self,
        *,
        scope_kind: ScopeKind,
        merchant_id: UUID | None,
        source_hashes: Sequence[str],
        target_locale: SupportedLocale,
        prompt_version: str,
    ) -> dict[str, MachineTranslationCache]:
        """两个公开入口的共用实现；本方法自身不对外暴露，调用方仍必须先经
        `get_merchant_machine_many()`/`get_global_machine_many()` 二选一决定
        `scope_kind`，不构成可以「忘记选作用域」的便利封装。

        `prompt_version` 精确匹配、不做「取最新」的模糊回退：`upsert_machine()`
        在 prompt 改版后会为同一源哈希新开一行（写侧唯一键含
        `prompt_version`），如果读侧不按 `prompt_version` 过滤，旧提示词产出
        的译文会在提示词改版后依然被当作"缓存命中"返回，写侧靠
        `prompt_version` 隔离失效译文的设计就形同虚设。调用方必须显式声明
        自己想要哪一版提示词产出的缓存。

        `source_language` 有意不作为过滤条件：它和 `source_hash` 同属对同一段
        源文本的确定性派生（`source_hash` 是该文本的哈希，`source_language`
        是 `detect_source_language()` 对同一文本的分类结果），因此在不发生
        哈希碰撞的前提下，同一个 `source_hash` 对应的 `source_language` 永远
        唯一——加这个过滤条件不会改变结果集。更关键的是，一次批量查询的
        `source_hashes` 通常横跨多段不同语言的源文本，`source_language` 天然
        是"逐条"属性而不是"整批"属性，不能像 `prompt_version`（整批查询共用
        同一个提示词版本）一样提升成方法级参数。"""

        if not source_hashes:
            return {}

        conditions = [
            MachineTranslationCache.scope_kind == scope_kind,
            MachineTranslationCache.source_hash.in_(list(source_hashes)),
            MachineTranslationCache.target_locale == str(target_locale),
            MachineTranslationCache.prompt_version == prompt_version,
        ]
        if scope_kind == "MERCHANT":
            conditions.append(MachineTranslationCache.merchant_id == merchant_id)
        else:
            conditions.append(MachineTranslationCache.merchant_id.is_(None))

        # 作用域 + 源哈希 + 源语言 + 目标语言 + prompt_version 是写侧的唯一键
        # （见 0015 迁移的两条按 scope_kind 拆分的表达式唯一索引）；这里已经
        # 精确匹配了除 source_language 外的全部维度，按上面的说明，同一
        # source_hash 不会有第二个不同的 source_language，所以命中集合里每个
        # source_hash 至多一行。`updated_at DESC` 排序 + 「同一 source_hash 只
        # 取第一条」只是防御性写法，不代表业务上允许「随便挑最新一条」。
        statement = (
            select(MachineTranslationCache)
            .where(*conditions)
            .order_by(MachineTranslationCache.updated_at.desc())
        )
        rows = list((await self._session.execute(statement)).scalars())

        hits: dict[str, MachineTranslationCache] = {}
        hit_ids: list[UUID] = []
        for row in rows:
            if row.source_hash in hits:
                continue
            hits[row.source_hash] = row
            hit_ids.append(row.id)

        if hit_ids:
            await self._session.execute(
                update(MachineTranslationCache)
                .where(MachineTranslationCache.id.in_(hit_ids))
                .values(last_accessed_at=func.now())
            )

        return hits

    async def upsert_machine(
        self,
        *,
        merchant_id: UUID | None,
        source_hash: str,
        source_language: SourceLanguage,
        target_locale: SupportedLocale,
        translated_text: str,
        model: str,
        prompt_version: str = "v1",
    ) -> MachineTranslationCache:
        """`merchant_id` 为 `None` 写入 GLOBAL 缓存，否则写入该商家的
        MERCHANT 缓存；命中已存在的 (作用域, 源哈希, 源语言, 目标语言,
        prompt_version) 时覆盖译文并把 30 天过期延后到本次写入起算。"""

        scope_kind: ScopeKind = "MERCHANT" if merchant_id is not None else "GLOBAL"
        if scope_kind == "MERCHANT":
            index_elements = [
                "merchant_id",
                "source_hash",
                "source_language",
                "target_locale",
                "prompt_version",
            ]
        else:
            index_elements = ["source_hash", "source_language", "target_locale", "prompt_version"]

        expires_at = text("now() + interval '30 days'")
        statement = (
            insert(MachineTranslationCache)
            .values(
                scope_kind=scope_kind,
                merchant_id=merchant_id,
                source_hash=source_hash,
                source_language=str(source_language),
                target_locale=str(target_locale),
                translated_text=translated_text,
                model=model,
                prompt_version=prompt_version,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                index_elements=index_elements,
                index_where=text(f"scope_kind = '{scope_kind}'"),
                set_={
                    "translated_text": translated_text,
                    "model": model,
                    "updated_at": func.now(),
                    "last_accessed_at": func.now(),
                    "expires_at": expires_at,
                },
            )
            .returning(MachineTranslationCache)
        )
        # 与 `MerchantMemoryRepository.upsert` 同一原因：RETURNING 复用 identity map
        # 内实例时不会自动带回本次覆盖后的字段，需要显式 refresh。
        row = (await self._session.execute(statement)).scalar_one()
        await self._session.refresh(row)
        return row

    async def delete_machine_by_hashes(
        self,
        *,
        scope: LocalizationScope,
        source_hashes: Sequence[str],
    ) -> int:
        """按显式作用域删除指定源哈希的机器缓存；用于业务资源删除时清理可
        定位的派生缓存。返回实际删除行数。"""

        _validate_scope(scope)
        if not source_hashes:
            return 0

        conditions = [
            MachineTranslationCache.scope_kind == scope.kind,
            MachineTranslationCache.source_hash.in_(list(source_hashes)),
        ]
        if scope.kind == "MERCHANT":
            conditions.append(MachineTranslationCache.merchant_id == scope.merchant_id)
        else:
            conditions.append(MachineTranslationCache.merchant_id.is_(None))

        result = cast(
            "CursorResult[Any]",
            await self._session.execute(delete(MachineTranslationCache).where(*conditions)),
        )
        return result.rowcount or 0

    async def purge_expired_machine(self, *, now: datetime | None = None) -> int:
        """批量清理已过期的机器缓存，不区分作用域或商家。返回删除行数。"""

        cutoff = now or datetime.now(UTC)
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                delete(MachineTranslationCache).where(MachineTranslationCache.expires_at <= cutoff)
            ),
        )
        return result.rowcount or 0

    # ------------------------------------------------------------------
    # 资源级人工译文
    # ------------------------------------------------------------------

    async def get_current_resource_translation(
        self,
        *,
        scope: LocalizationScope,
        key: ResourceLocalizationKey,
        target_locale: SupportedLocale,
        current_source_hash: str,
        current_source_version: int,
    ) -> ResourceTranslationLookup:
        """按 `key` + `target_locale` 精确定位人工译文，并与调用方传入的当前
        源内容指纹（`current_source_hash`/`current_source_version`）比对：
        一致为 `CURRENT`，存在但不一致为 `STALE`（仍带回旧译文供审计/展示
        降级用，调用方必须自行判断是否可以直接渲染），不存在为 `MISSING`。"""

        _validate_scope(scope)

        conditions = [
            ResourceLocalization.scope_kind == scope.kind,
            ResourceLocalization.resource_type == key.resource_type,
            ResourceLocalization.resource_id == key.resource_id,
            ResourceLocalization.field_name == key.field_name,
            ResourceLocalization.target_locale == str(target_locale),
        ]
        if scope.kind == "MERCHANT":
            conditions.append(ResourceLocalization.merchant_id == scope.merchant_id)
        else:
            conditions.append(ResourceLocalization.merchant_id.is_(None))

        statement = select(ResourceLocalization).where(*conditions)
        record = (await self._session.execute(statement)).scalar_one_or_none()

        if record is None:
            return ResourceTranslationLookup(status=ResourceLocalizationStatus.MISSING, record=None)
        if (
            record.source_hash == current_source_hash
            and record.source_version == current_source_version
        ):
            return ResourceTranslationLookup(
                status=ResourceLocalizationStatus.CURRENT, record=record
            )
        return ResourceTranslationLookup(status=ResourceLocalizationStatus.STALE, record=record)

    async def upsert_human(
        self,
        *,
        scope: LocalizationScope,
        key: ResourceLocalizationKey,
        target_locale: SupportedLocale,
        source_hash: str,
        source_version: int,
        source_language: SourceLanguage,
        translated_text: str,
    ) -> ResourceLocalization:
        """保存人工确认译文，覆盖同 (作用域, 资源类型, 资源 ID, 字段,
        目标语言) 下的旧版本，并刷新快照的 `source_hash`/`source_version`，
        使旧的 `STALE` 判定在写入后立即变回 `CURRENT`。"""

        _validate_scope(scope)
        if scope.kind == "MERCHANT":
            index_elements = [
                "merchant_id",
                "resource_type",
                "resource_id",
                "field_name",
                "target_locale",
            ]
        else:
            index_elements = ["resource_type", "resource_id", "field_name", "target_locale"]

        statement = (
            insert(ResourceLocalization)
            .values(
                scope_kind=scope.kind,
                merchant_id=scope.merchant_id,
                resource_type=key.resource_type,
                resource_id=key.resource_id,
                field_name=key.field_name,
                target_locale=str(target_locale),
                source_hash=source_hash,
                source_version=source_version,
                source_language=str(source_language),
                translated_text=translated_text,
            )
            .on_conflict_do_update(
                index_elements=index_elements,
                index_where=text(f"scope_kind = '{scope.kind}'"),
                set_={
                    "source_hash": source_hash,
                    "source_version": source_version,
                    "source_language": str(source_language),
                    "translated_text": translated_text,
                    "updated_at": func.now(),
                },
            )
            .returning(ResourceLocalization)
        )
        record = (await self._session.execute(statement)).scalar_one()
        await self._session.refresh(record)
        return record

    async def delete_resource_localizations(
        self,
        *,
        resource_type: str,
        resource_id: UUID,
    ) -> int:
        """删除某资源在所有作用域、所有字段、所有目标语言下的人工译文。用于
        知识文档/商家记忆被删除时，由调用方 Service 在同一事务里显式调用，
        本仓储不监听其它表的删除事件。返回删除行数。"""

        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                delete(ResourceLocalization).where(
                    ResourceLocalization.resource_type == resource_type,
                    ResourceLocalization.resource_id == resource_id,
                )
            ),
        )
        return result.rowcount or 0
