"""`LocalizationRepository` 的商家隔离与译文语义。

覆盖点：
- 机器缓存严格按 (作用域, 商家) 隔离，商家 A 写入的缓存对商家 B 不可见；
- 两个资源即便拥有完全相同的原文，人工译文也互不复用，只按
  (作用域, 资源类型, 资源 ID, 字段, 目标语言) 精确匹配；
- 资源的 `source_hash`/`source_version` 更新后，旧人工译文读回 `STALE`
  而不是被当作当前译文冒充返回；
- 删除资源后，Service 层显式清理 `resource_localizations` 的行为在
  Repository 一侧可验证（`delete_resource_localizations()`）；
- `purge_expired_machine()` 能清掉过期的机器缓存，不影响未过期的行。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.localization.locales import SourceLanguage, SupportedLocale
from app.models.merchant import Merchant
from app.repositories.localization import (
    LocalizationRepository,
    LocalizationScope,
    ResourceLocalizationKey,
    ResourceLocalizationStatus,
)


@pytest_asyncio.fixture
async def merchant_a(db_session: AsyncSession) -> Merchant:
    merchant = Merchant(
        id=uuid4(),
        merchant_code="localization-repository-merchant-a",
        display_name="本地化仓储商家 A",
    )
    db_session.add(merchant)
    await db_session.flush()
    return merchant


@pytest_asyncio.fixture
async def merchant_b(db_session: AsyncSession) -> Merchant:
    merchant = Merchant(
        id=uuid4(),
        merchant_code="localization-repository-merchant-b",
        display_name="本地化仓储商家 B",
    )
    db_session.add(merchant)
    await db_session.flush()
    return merchant


# ---------------------------------------------------------------------------
# 机器译文缓存：作用域隔离
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_translation_cache_is_scoped_by_merchant(
    db_session: AsyncSession,
    merchant_a: Merchant,
    merchant_b: Merchant,
) -> None:
    repo = LocalizationRepository(db_session)
    await repo.upsert_machine(
        merchant_id=merchant_a.id,
        source_hash="a" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="Refund amount",
        model="fake",
    )
    await db_session.flush()

    assert (
        await repo.get_merchant_machine_many(
            merchant_id=merchant_b.id,
            source_hashes=["a" * 64],
            target_locale=SupportedLocale.EN_US,
        )
        == {}
    )


@pytest.mark.asyncio
async def test_translation_cache_is_visible_to_owning_merchant(
    db_session: AsyncSession,
    merchant_a: Merchant,
) -> None:
    repo = LocalizationRepository(db_session)
    await repo.upsert_machine(
        merchant_id=merchant_a.id,
        source_hash="a" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="Refund amount",
        model="fake",
    )
    await db_session.flush()

    hits = await repo.get_merchant_machine_many(
        merchant_id=merchant_a.id,
        source_hashes=["a" * 64],
        target_locale=SupportedLocale.EN_US,
    )

    assert set(hits) == {"a" * 64}
    assert hits["a" * 64].translated_text == "Refund amount"


@pytest.mark.asyncio
async def test_global_machine_cache_never_returned_by_merchant_lookup(
    db_session: AsyncSession,
    merchant_a: Merchant,
) -> None:
    repo = LocalizationRepository(db_session)
    await repo.upsert_machine(
        merchant_id=None,
        source_hash="b" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="Platform-wide copy",
        model="fake",
    )
    await db_session.flush()

    assert (
        await repo.get_merchant_machine_many(
            merchant_id=merchant_a.id,
            source_hashes=["b" * 64],
            target_locale=SupportedLocale.EN_US,
        )
        == {}
    )
    global_hits = await repo.get_global_machine_many(
        source_hashes=["b" * 64], target_locale=SupportedLocale.EN_US
    )
    assert global_hits["b" * 64].translated_text == "Platform-wide copy"


@pytest.mark.asyncio
async def test_upsert_machine_overwrites_same_scope_key(
    db_session: AsyncSession,
    merchant_a: Merchant,
) -> None:
    repo = LocalizationRepository(db_session)
    await repo.upsert_machine(
        merchant_id=merchant_a.id,
        source_hash="c" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="first",
        model="fake",
    )
    await db_session.flush()
    await repo.upsert_machine(
        merchant_id=merchant_a.id,
        source_hash="c" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="second",
        model="fake",
    )
    await db_session.flush()

    hits = await repo.get_merchant_machine_many(
        merchant_id=merchant_a.id,
        source_hashes=["c" * 64],
        target_locale=SupportedLocale.EN_US,
    )
    assert len(hits) == 1
    assert hits["c" * 64].translated_text == "second"


@pytest.mark.asyncio
async def test_delete_machine_by_hashes_only_affects_targeted_scope(
    db_session: AsyncSession,
    merchant_a: Merchant,
    merchant_b: Merchant,
) -> None:
    repo = LocalizationRepository(db_session)
    await repo.upsert_machine(
        merchant_id=merchant_a.id,
        source_hash="d" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="a's cache",
        model="fake",
    )
    await repo.upsert_machine(
        merchant_id=merchant_b.id,
        source_hash="d" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="b's cache",
        model="fake",
    )
    await db_session.flush()

    deleted = await repo.delete_machine_by_hashes(
        scope=LocalizationScope(kind="MERCHANT", merchant_id=merchant_a.id),
        source_hashes=["d" * 64],
    )
    await db_session.flush()

    assert deleted == 1
    assert (
        await repo.get_merchant_machine_many(
            merchant_id=merchant_a.id,
            source_hashes=["d" * 64],
            target_locale=SupportedLocale.EN_US,
        )
        == {}
    )
    remaining = await repo.get_merchant_machine_many(
        merchant_id=merchant_b.id,
        source_hashes=["d" * 64],
        target_locale=SupportedLocale.EN_US,
    )
    assert remaining["d" * 64].translated_text == "b's cache"


@pytest.mark.asyncio
async def test_purge_expired_machine_only_removes_expired_rows(
    db_session: AsyncSession,
    merchant_a: Merchant,
) -> None:
    repo = LocalizationRepository(db_session)
    fresh = await repo.upsert_machine(
        merchant_id=merchant_a.id,
        source_hash="e" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="still valid",
        model="fake",
    )
    stale = await repo.upsert_machine(
        merchant_id=merchant_a.id,
        source_hash="f" * 64,
        source_language=SourceLanguage.ZH_CN,
        target_locale=SupportedLocale.EN_US,
        translated_text="30 days old",
        model="fake",
    )
    # 直接改写 expires_at 模拟已过期的历史缓存行，而不是等待真实 30 天。
    await db_session.execute(
        text("UPDATE machine_translation_cache SET expires_at = :expires_at WHERE id = :id"),
        {"expires_at": datetime.now(UTC) - timedelta(days=1), "id": stale.id},
    )
    await db_session.flush()

    deleted = await repo.purge_expired_machine(now=datetime.now(UTC))
    await db_session.flush()

    assert deleted == 1
    remaining = await repo.get_merchant_machine_many(
        merchant_id=merchant_a.id,
        source_hashes=["e" * 64, "f" * 64],
        target_locale=SupportedLocale.EN_US,
    )
    assert set(remaining) == {"e" * 64}
    assert remaining["e" * 64].translated_text == "still valid"
    assert fresh.id != stale.id


# ---------------------------------------------------------------------------
# 资源级人工译文：跨资源不复用 + 过期检测
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_translation_on_document_a_not_matched_by_document_b(
    db_session: AsyncSession,
    merchant_a: Merchant,
) -> None:
    """两份知识文档原文完全相同,但各自的人工译文互不复用——必须按
    resource_id 精确匹配,不能按纯文本内容对齐。"""

    repo = LocalizationRepository(db_session)
    scope = LocalizationScope(kind="GLOBAL")
    document_a = uuid4()
    document_b = uuid4()
    same_source_hash = "g" * 64

    await repo.upsert_human(
        scope=scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_a, field_name="content"
        ),
        target_locale=SupportedLocale.EN_US,
        source_hash=same_source_hash,
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="Document A official translation",
    )
    await db_session.flush()

    lookup_b = await repo.get_current_resource_translation(
        scope=scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_b, field_name="content"
        ),
        target_locale=SupportedLocale.EN_US,
        current_source_hash=same_source_hash,
        current_source_version=1,
    )

    assert lookup_b.status is ResourceLocalizationStatus.MISSING
    assert lookup_b.record is None

    lookup_a = await repo.get_current_resource_translation(
        scope=scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_a, field_name="content"
        ),
        target_locale=SupportedLocale.EN_US,
        current_source_hash=same_source_hash,
        current_source_version=1,
    )
    assert lookup_a.status is ResourceLocalizationStatus.CURRENT
    assert lookup_a.record is not None
    assert lookup_a.record.translated_text == "Document A official translation"


@pytest.mark.asyncio
async def test_stale_human_translation_is_flagged_not_served_as_current(
    db_session: AsyncSession,
) -> None:
    """文档源内容更新(哈希/版本变化)后,旧人工译文必须回报 STALE,不能被当作
    当前有效译文直接返回。"""

    repo = LocalizationRepository(db_session)
    scope = LocalizationScope(kind="GLOBAL")
    document_id = uuid4()
    key = ResourceLocalizationKey(
        resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_id, field_name="content"
    )

    await repo.upsert_human(
        scope=scope,
        key=key,
        target_locale=SupportedLocale.EN_US,
        source_hash="h" * 64,
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="Translated against v1",
    )
    await db_session.flush()

    # 源文档正文改了(新版本、新哈希),但人工译文还没人跟进重译。
    lookup = await repo.get_current_resource_translation(
        scope=scope,
        key=key,
        target_locale=SupportedLocale.EN_US,
        current_source_hash="i" * 64,
        current_source_version=2,
    )

    assert lookup.status is ResourceLocalizationStatus.STALE
    assert lookup.record is not None
    assert lookup.record.translated_text == "Translated against v1"


@pytest.mark.asyncio
async def test_upsert_human_refreshes_stale_back_to_current(
    db_session: AsyncSession,
) -> None:
    repo = LocalizationRepository(db_session)
    scope = LocalizationScope(kind="GLOBAL")
    document_id = uuid4()
    key = ResourceLocalizationKey(
        resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_id, field_name="content"
    )

    await repo.upsert_human(
        scope=scope,
        key=key,
        target_locale=SupportedLocale.EN_US,
        source_hash="j" * 64,
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="v1 translation",
    )
    await db_session.flush()

    await repo.upsert_human(
        scope=scope,
        key=key,
        target_locale=SupportedLocale.EN_US,
        source_hash="k" * 64,
        source_version=2,
        source_language=SourceLanguage.ZH_CN,
        translated_text="v2 translation",
    )
    await db_session.flush()

    lookup = await repo.get_current_resource_translation(
        scope=scope,
        key=key,
        target_locale=SupportedLocale.EN_US,
        current_source_hash="k" * 64,
        current_source_version=2,
    )
    assert lookup.status is ResourceLocalizationStatus.CURRENT
    assert lookup.record is not None
    assert lookup.record.translated_text == "v2 translation"


@pytest.mark.asyncio
async def test_merchant_scoped_human_translation_isolated_across_merchants(
    db_session: AsyncSession,
    merchant_a: Merchant,
    merchant_b: Merchant,
) -> None:
    """商家记忆等 MERCHANT 作用域资源的人工译文同样必须按商家隔离,即便两个
    商家碰巧使用了同一个 resource_id(理论上不会发生,但仍要在数据库层面
    锁定该不变式,不能只依赖 resource_id 全局唯一这一假设)。"""

    repo = LocalizationRepository(db_session)
    shared_resource_id = uuid4()
    key = ResourceLocalizationKey(
        resource_type="MERCHANT_MEMORY", resource_id=shared_resource_id, field_name="content"
    )

    await repo.upsert_human(
        scope=LocalizationScope(kind="MERCHANT", merchant_id=merchant_a.id),
        key=key,
        target_locale=SupportedLocale.EN_US,
        source_hash="l" * 64,
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="merchant a memory translation",
    )
    await db_session.flush()

    lookup_for_b = await repo.get_current_resource_translation(
        scope=LocalizationScope(kind="MERCHANT", merchant_id=merchant_b.id),
        key=key,
        target_locale=SupportedLocale.EN_US,
        current_source_hash="l" * 64,
        current_source_version=1,
    )

    assert lookup_for_b.status is ResourceLocalizationStatus.MISSING


@pytest.mark.asyncio
async def test_delete_resource_localizations_removes_all_fields_and_locales(
    db_session: AsyncSession,
) -> None:
    """删除文档/记忆时,Service 必须在同一事务显式清理该资源的全部派生译文
    (不论 field_name 或 target_locale)——本用例锁定 Repository 一侧的删除
    行为覆盖面。"""

    repo = LocalizationRepository(db_session)
    scope = LocalizationScope(kind="GLOBAL")
    document_id = uuid4()

    await repo.upsert_human(
        scope=scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_id, field_name="title"
        ),
        target_locale=SupportedLocale.EN_US,
        source_hash="m" * 64,
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="Title EN",
    )
    await repo.upsert_human(
        scope=scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_id, field_name="content"
        ),
        target_locale=SupportedLocale.EN_US,
        source_hash="n" * 64,
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="Content EN",
    )
    await db_session.flush()

    deleted = await repo.delete_resource_localizations(
        resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_id
    )
    await db_session.flush()

    assert deleted == 2
    for field_name in ("title", "content"):
        lookup = await repo.get_current_resource_translation(
            scope=scope,
            key=ResourceLocalizationKey(
                resource_type="KNOWLEDGE_DOCUMENT",
                resource_id=document_id,
                field_name=field_name,  # type: ignore[arg-type]
            ),
            target_locale=SupportedLocale.EN_US,
            current_source_hash="m" * 64,
            current_source_version=1,
        )
        assert lookup.status is ResourceLocalizationStatus.MISSING


@pytest.mark.asyncio
async def test_delete_resource_localizations_does_not_affect_other_resources(
    db_session: AsyncSession,
) -> None:
    repo = LocalizationRepository(db_session)
    scope = LocalizationScope(kind="GLOBAL")
    document_a = uuid4()
    document_b = uuid4()

    await repo.upsert_human(
        scope=scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_a, field_name="content"
        ),
        target_locale=SupportedLocale.EN_US,
        source_hash="o" * 64,
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="doc a",
    )
    await repo.upsert_human(
        scope=scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_b, field_name="content"
        ),
        target_locale=SupportedLocale.EN_US,
        source_hash="p" * 64,
        source_version=1,
        source_language=SourceLanguage.ZH_CN,
        translated_text="doc b",
    )
    await db_session.flush()

    await repo.delete_resource_localizations(
        resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_a
    )
    await db_session.flush()

    lookup_b = await repo.get_current_resource_translation(
        scope=scope,
        key=ResourceLocalizationKey(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_b, field_name="content"
        ),
        target_locale=SupportedLocale.EN_US,
        current_source_hash="p" * 64,
        current_source_version=1,
    )
    assert lookup_b.status is ResourceLocalizationStatus.CURRENT
    assert lookup_b.record is not None
    assert lookup_b.record.translated_text == "doc b"


# ---------------------------------------------------------------------------
# 强制作用域接口:CHECK 约束在应用层的第二道防线
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_localization_scope_rejects_merchant_without_merchant_id(
    db_session: AsyncSession,
) -> None:
    repo = LocalizationRepository(db_session)
    with pytest.raises(ValueError):
        await repo.delete_machine_by_hashes(
            scope=LocalizationScope(kind="MERCHANT", merchant_id=None),
            source_hashes=["q" * 64],
        )


@pytest.mark.asyncio
async def test_localization_scope_rejects_global_with_merchant_id(
    db_session: AsyncSession,
    merchant_a: Merchant,
) -> None:
    repo = LocalizationRepository(db_session)
    with pytest.raises(ValueError):
        await repo.delete_machine_by_hashes(
            scope=LocalizationScope(kind="GLOBAL", merchant_id=merchant_a.id),
            source_hashes=["r" * 64],
        )
