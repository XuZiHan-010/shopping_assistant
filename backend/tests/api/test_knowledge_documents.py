"""文档 CRUD 与 428/412 乐观锁。"""

from __future__ import annotations

import asyncio

from httpx import AsyncClient


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
