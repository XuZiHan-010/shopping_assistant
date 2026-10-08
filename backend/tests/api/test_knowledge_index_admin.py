"""知识后台接入索引版本（N4-C Task 6，PRD M12、§7.6，契约 §8.6.7）。

- 目录树返回索引状态；
- 文档写入在同一事务里标陈旧，提交后后台重建新版本，旧版本在此期间继续服务；
- 人工译文不进索引，不触发重建；
- 构建失败时旧版本仍生效且陈旧原因可见。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.knowledge.index_versions import KnowledgeIndexService
from tests.support.fake_embedders import BigramEmbedder, FailingEmbedder

TREE = "/api/admin/knowledge/tree"
DOCS = "/api/admin/knowledge/documents"


def _use_embedder(app: FastAPI, embedder: object) -> KnowledgeIndexService:
    service = KnowledgeIndexService(app.state.database, embedder)  # type: ignore[arg-type]
    app.state.knowledge_index = service
    return service


async def _status(client: AsyncClient) -> dict[str, object]:
    response = await client.get(TREE)
    assert response.status_code == 200, response.text
    status = response.json()["index_status"]
    assert isinstance(status, dict)
    return status


@pytest.mark.asyncio
async def test_tree_reports_keyword_only_when_nothing_was_built(admin_client: AsyncClient) -> None:
    assert await _status(admin_client) == {
        "retrieval_mode": "KEYWORD_ONLY",
        "active_version": None,
        "embedding_model": None,
        "configured_model": None,
        "stale": False,
        "stale_reason": None,
        "building": False,
        "last_failure_reason": None,
    }


@pytest.mark.asyncio
async def test_saving_a_document_builds_and_activates_a_new_version(
    knowledge_admin_app: FastAPI, admin_client: AsyncClient, existing_document: str
) -> None:
    service = _use_embedder(knowledge_admin_app, BigramEmbedder())
    first = await service.build()
    etag = (await admin_client.get(f"{DOCS}/{existing_document}")).headers["etag"]

    response = await admin_client.put(
        f"{DOCS}/{existing_document}",
        json={"content": "退货运费由平台承担（修订）"},
        headers={"If-Match": etag},
    )
    assert response.status_code == 200, response.text

    # ASGI 测试传输会等后台任务跑完再返回：新版本已生效、陈旧标记已清除。
    status = await _status(admin_client)
    assert status["active_version"] not in (None, first.version_id)
    assert status["retrieval_mode"] == "HYBRID"
    assert status["stale"] is False and status["configured_model"] == "fake-bigram"


@pytest.mark.asyncio
async def test_write_marks_stale_in_the_same_transaction(
    knowledge_admin_app: FastAPI, admin_client: AsyncClient
) -> None:
    """未配置模型时不会重建：此时看到的陈旧标记只能来自写入事务本身。"""

    good = _use_embedder(knowledge_admin_app, BigramEmbedder())
    await admin_client.post(DOCS, json={"path": "index/规则.md", "content": "退货运费规则"})
    first = await good.build()
    _use_embedder(knowledge_admin_app, None)

    response = await admin_client.post(DOCS, json={"path": "index/新增.md", "content": "新增规则"})
    assert response.status_code == 201, response.text

    status = await _status(admin_client)
    assert status["active_version"] == first.version_id
    assert status["stale"] is True and status["stale_reason"] == "CORPUS_CHANGED"
    assert status["retrieval_mode"] == "KEYWORD_ONLY"  # 配置里没有模型，就不能声称混合检索


@pytest.mark.asyncio
async def test_failed_rebuild_keeps_old_version_and_shows_why(
    knowledge_admin_app: FastAPI, admin_client: AsyncClient
) -> None:
    good = _use_embedder(knowledge_admin_app, BigramEmbedder())
    await admin_client.post(DOCS, json={"path": "index/规则.md", "content": "退货运费规则"})
    first = await good.build()
    _use_embedder(knowledge_admin_app, FailingEmbedder())

    response = await admin_client.post(DOCS, json={"path": "index/新增.md", "content": "新增规则"})
    assert response.status_code == 201, response.text

    status = await _status(admin_client)
    assert status["active_version"] == first.version_id
    assert status["stale"] is True and status["stale_reason"] == "BUILD_FAILED"
    assert status["last_failure_reason"] == "EMBEDDING_FAILED"


@pytest.mark.asyncio
async def test_translation_save_does_not_touch_the_index(
    knowledge_admin_app: FastAPI, admin_client: AsyncClient, existing_document: str
) -> None:
    service = _use_embedder(knowledge_admin_app, BigramEmbedder())
    first = await service.build()
    etag = (await admin_client.get(f"{DOCS}/{existing_document}")).headers["etag"]

    response = await admin_client.put(
        f"{DOCS}/{existing_document}",
        json={"content": "Original content", "is_source_version": False, "content_locale": "en-US"},
        headers={"If-Match": etag},
    )
    assert response.status_code == 200, response.text
    status = await _status(admin_client)
    assert status["active_version"] == first.version_id and status["stale"] is False


@pytest.mark.asyncio
async def test_deleting_a_document_rebuilds_without_it(
    knowledge_admin_app: FastAPI, admin_client: AsyncClient, existing_document: str
) -> None:
    service = _use_embedder(knowledge_admin_app, BigramEmbedder())
    await admin_client.post(DOCS, json={"path": "index/保留.md", "content": "保留的规则"})
    first = await service.build()
    etag = (await admin_client.get(f"{DOCS}/{existing_document}")).headers["etag"]

    response = await admin_client.delete(f"{DOCS}/{existing_document}", headers={"If-Match": etag})
    assert response.status_code == 204
    status = await _status(admin_client)
    assert status["active_version"] != first.version_id and status["stale"] is False
