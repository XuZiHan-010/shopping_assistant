"""文档 CRUD 与 428/412 乐观锁。"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from httpx import AsyncClient

from app.localization.locales import SupportedLocale
from app.repositories.knowledge_admin import KnowledgeAdminRepository
from app.repositories.localization import (
    LocalizationRepository,
    LocalizationScope,
    ResourceLocalizationKey,
    ResourceLocalizationStatus,
)


async def test_create_returns_etag(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "index/新文档.md", "content": "# 标题"},
    )

    assert response.status_code == 201
    assert response.headers["etag"].startswith('"')


async def test_create_rejects_duplicate(admin_client: AsyncClient, existing_document: str) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": existing_document, "content": "x"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "WIKI_NODE_EXISTS"


async def test_create_rejects_case_insensitive_duplicate(admin_client: AsyncClient) -> None:
    await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "index/Readme.md", "content": "a"},
    )
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "index/readme.md", "content": "b"},
    )

    assert response.status_code == 409


async def test_update_without_if_match_returns_428(
    admin_client: AsyncClient, existing_document: str
) -> None:
    response = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={"content": "新内容"},
    )

    assert response.status_code == 428
    assert response.json()["code"] == "WIKI_VERSION_REQUIRED"


async def test_update_with_stale_if_match_returns_412(
    admin_client: AsyncClient, existing_document: str
) -> None:
    response = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={"content": "新内容"},
        headers={"If-Match": '"deadbeef"'},
    )

    assert response.status_code == 412
    assert response.json()["code"] == "WIKI_VERSION_CONFLICT"


async def test_update_with_weak_etag_is_accepted(
    admin_client: AsyncClient, existing_document: str
) -> None:
    current = (
        await admin_client.get(f"/api/admin/knowledge/documents/{existing_document}")
    ).headers["etag"]

    response = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={"content": "新内容"},
        headers={"If-Match": f"W/{current}"},
    )

    assert response.status_code == 200


async def test_concurrent_updates_with_same_etag_allow_only_one_writer(
    admin_client: AsyncClient, existing_document: str
) -> None:
    """ETag 必须落到条件 UPDATE，不能只在应用层先读后比对。"""

    etag = (await admin_client.get(f"/api/admin/knowledge/documents/{existing_document}")).headers[
        "etag"
    ]

    first, second = await asyncio.gather(
        admin_client.put(
            f"/api/admin/knowledge/documents/{existing_document}",
            json={"content": "并发写入甲"},
            headers={"If-Match": etag},
        ),
        admin_client.put(
            f"/api/admin/knowledge/documents/{existing_document}",
            json={"content": "并发写入乙"},
            headers={"If-Match": etag},
        ),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 412]


async def test_content_with_nul_is_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "index/坏文档.md", "content": "a\x00b"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_WIKI_CONTENT"


async def test_oversized_content_is_rejected(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "index/大文档.md", "content": "x" * 262_145},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "WIKI_DOCUMENT_TOO_LARGE"


async def test_writing_into_memory_is_forbidden(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": "memory/merchants/abc/TRADE.md", "content": "x"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "WIKI_READ_ONLY"


async def test_delete_requires_if_match(admin_client: AsyncClient, existing_document: str) -> None:
    response = await admin_client.delete(f"/api/admin/knowledge/documents/{existing_document}")
    assert response.status_code == 428


# ---------------------------------------------------------------------------
# Task 8 Step 4：源版本 / 人工译文版本分离
# ---------------------------------------------------------------------------


async def _current_version(admin_client: AsyncClient, path: str) -> str:
    return (await admin_client.get(f"/api/admin/knowledge/documents/{path}")).headers["etag"]


async def test_editing_english_version_does_not_overwrite_chinese_source(
    admin_client: AsyncClient, existing_document: str
) -> None:
    """brief Step 1 原文场景：`existing_document` 固件的源正文是"原内容"
    （中文）；保存一份 `is_source_version=false` 的英文人工译文后，源正文
    必须原样不变，读取 en-US 必须拿到刚保存的英文内容。"""

    etag = await _current_version(admin_client, existing_document)

    response = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={
            "content": "English policy",
            "is_source_version": False,
            "content_locale": "en-US",
        },
        headers={"If-Match": etag},
    )
    assert response.status_code == 200, response.text
    assert response.json()["content"] == "English policy"
    assert response.json()["content_locale"] == "en-US"
    assert response.json()["translation_status"] == "CURRENT"

    zh_read = await admin_client.get(
        f"/api/admin/knowledge/documents/{existing_document}",
        params={"content_locale": "zh-CN"},
    )
    en_read = await admin_client.get(
        f"/api/admin/knowledge/documents/{existing_document}",
        params={"content_locale": "en-US"},
    )
    assert zh_read.json()["content"] == "原内容"
    assert zh_read.json()["translation_status"] == "SOURCE"
    assert en_read.json()["content"] == "English policy"
    assert en_read.json()["translation_status"] == "CURRENT"


async def test_content_locale_is_required_for_a_human_translation_edit(
    admin_client: AsyncClient, existing_document: str
) -> None:
    etag = await _current_version(admin_client, existing_document)

    response = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={"content": "English policy", "is_source_version": False},
        headers={"If-Match": etag},
    )

    assert response.status_code == 422


async def test_reading_without_a_saved_translation_falls_back_to_source_as_missing(
    admin_client: AsyncClient, existing_document: str
) -> None:
    response = await admin_client.get(
        f"/api/admin/knowledge/documents/{existing_document}",
        params={"content_locale": "en-US"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "原内容"
    assert response.json()["translation_status"] == "MISSING"
    assert response.json()["content_locale"] == "zh-CN"


async def test_editing_the_source_flips_an_existing_human_translation_to_stale(
    admin_client: AsyncClient, existing_document: str
) -> None:
    """源内容变化后，旧的人工译文不会被删除，但读取时不能再当作 CURRENT
    展示——必须回退到（新的）源正文并标成 STALE（Step 4 原文）。"""

    etag = await _current_version(admin_client, existing_document)
    await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={
            "content": "English policy",
            "is_source_version": False,
            "content_locale": "en-US",
        },
        headers={"If-Match": etag},
    )

    source_etag = await _current_version(admin_client, existing_document)
    updated_source = await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={"content": "更新后的中文规则", "is_source_version": True},
        headers={"If-Match": source_etag},
    )
    assert updated_source.status_code == 200, updated_source.text
    assert updated_source.json()["content"] == "更新后的中文规则"
    assert updated_source.json()["translation_status"] == "SOURCE"

    stale_read = await admin_client.get(
        f"/api/admin/knowledge/documents/{existing_document}",
        params={"content_locale": "en-US"},
    )
    assert stale_read.status_code == 200
    assert stale_read.json()["translation_status"] == "STALE"
    # STALE 不把过期译文当成当前内容展示——回退为（新的）源正文。
    assert stale_read.json()["content"] == "更新后的中文规则"
    assert stale_read.json()["content_locale"] == "zh-CN"


async def test_deleting_a_document_removes_its_saved_human_translation(
    admin_client: AsyncClient,
    knowledge_admin_app: FastAPI,
    existing_document: str,
) -> None:
    """复审 Finding 2：直接查 `resource_localizations`（按被删文档的旧 id）
    才能真正证明删除触发了级联清理——原断言只是拿新文档（不同 id）读一次,
    即使级联清理完全没跑，"新 id 找不到旧 id 存的译文"这件事本身也恒成立,
    测试会一样通过、根本证伪不了级联删除是否真的发生。"""

    etag = await _current_version(admin_client, existing_document)
    await admin_client.put(
        f"/api/admin/knowledge/documents/{existing_document}",
        json={
            "content": "English policy",
            "is_source_version": False,
            "content_locale": "en-US",
        },
        headers={"If-Match": etag},
    )

    async with knowledge_admin_app.state.database.session() as session:
        old_document = await KnowledgeAdminRepository(session).get_by_path(existing_document)
    assert old_document is not None
    old_document_id = old_document.id

    delete_etag = await _current_version(admin_client, existing_document)
    delete_response = await admin_client.delete(
        f"/api/admin/knowledge/documents/{existing_document}",
        headers={"If-Match": delete_etag},
    )
    assert delete_response.status_code == 204

    # 直接对着被删文档的旧 id 查 `resource_localizations`——这才是"级联删除
    # 真的执行了"的证据,不是靠"新文档 id 不同所以查不到"这种巧合。
    async with knowledge_admin_app.state.database.session() as session:
        lookup = await LocalizationRepository(session).get_current_resource_translation(
            scope=LocalizationScope(kind="GLOBAL"),
            key=ResourceLocalizationKey(
                resource_type="KNOWLEDGE_DOCUMENT",
                resource_id=old_document_id,
                field_name="content",
            ),
            target_locale=SupportedLocale.EN_US,
            # source_hash/source_version 在这里无关紧要：只要该资源在
            # `resource_localizations` 里还有任意一行，`get_current_resource_
            # translation()` 就会返回 CURRENT 或 STALE 而不是 MISSING——
            # 三者中只有 MISSING 代表"这一行已经被删干净"。
            current_source_hash="irrelevant-for-existence-check",
            current_source_version=1,
        )
    assert lookup.status is ResourceLocalizationStatus.MISSING
    assert lookup.record is None

    recreated = await admin_client.post(
        "/api/admin/knowledge/documents",
        json={"path": existing_document, "content": "全新中文正文"},
    )
    assert recreated.status_code == 201

    # 新文档是不同的资源（新 id），读取只会看到新文档自己的源正文
    # （MISSING，与上面按旧 id 的直接断言相互印证，不是唯一证据）。
    read_after_recreate = await admin_client.get(
        f"/api/admin/knowledge/documents/{existing_document}",
        params={"content_locale": "en-US"},
    )
    assert read_after_recreate.json()["content"] == "全新中文正文"
    assert read_after_recreate.json()["translation_status"] == "MISSING"
