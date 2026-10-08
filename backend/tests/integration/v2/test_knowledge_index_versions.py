"""知识索引版本状态机（PRD §7.6，契约 §6.14，计划 Task 2）——真实 PostgreSQL + pgvector。

覆盖四条必测：切换原子、失败保留旧版并标陈旧、无旧版降级为关键词并如实标注、质量回退阻止切换；
另测单构建互斥、文档变更标陈旧与旧版本分块回收。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.index_versions import (
    _SEARCH_SQL,
    INDEX_FALLBACK_REASON,
    INDEX_STALE_REASON,
    BuildResult,
    IndexFailureReason,
    IndexStatus,
    KnowledgeIndexService,
    VectorIndexSearch,
    mark_corpus_changed,
    vector_literal,
)
from app.knowledge.retrieval import KnowledgeRetrieval
from app.knowledge.wiki_seed import seed_wiki_documents
from app.repositories.knowledge import KnowledgeRepository
from app.tools.merchant.definitions import resolve_rule_search
from tests.support.fake_embedders import BigramEmbedder, FailingEmbedder, RandomEmbedder


@pytest.fixture
async def corpus(db_session: AsyncSession, integration_database: Database) -> Database:
    await seed_wiki_documents(integration_database)
    return integration_database


def _service(database: Database, embedder: object) -> KnowledgeIndexService:
    return KnowledgeIndexService(database, embedder)  # type: ignore[arg-type]


def _search(database: Database, embedder: object) -> VectorIndexSearch:
    return VectorIndexSearch(database, embedder, min_similarity=0.0)  # type: ignore[arg-type]


async def _active(database: Database) -> int | None:
    return (await _service(database, None).snapshot()).active_version_id


@pytest.mark.asyncio
async def test_first_build_activates_and_serves_vectors(corpus: Database) -> None:
    outcome = await _service(corpus, BigramEmbedder()).build()
    assert outcome.result is BuildResult.ACTIVATED and outcome.recall_at_5 is not None
    assert await _active(corpus) == outcome.version_id
    result = await _search(corpus, BigramEmbedder()).search("退货退款的流程是怎样的")
    assert result.status is IndexStatus.FRESH
    assert result.version_id == outcome.version_id and result.ranking


@pytest.mark.asyncio
async def test_switch_is_atomic(corpus: Database) -> None:
    """并发查询在切换瞬间只能看到**某一个版本的完整分块**（复审 F1 加强）。

    每次查询既断言只出现一个版本，也断言返回的文档数等于该版本的 `document_count`——
    「指针已指向新版本、分块却不完整」会让后者失败。多轮在两个 READY 版本之间来回切换，
    其间回收会并发删除旧版本分块；跨轮至少观察到两个不同版本，保证切换真的落在查询之间。
    """

    embedder = BigramEmbedder()
    service = _service(corpus, embedder)
    await service.build()
    second = await service.build(activate=False)
    third = await service.build(activate=False)
    assert second.version_id is not None and third.version_id is not None
    async with corpus.session() as session:
        expected = {
            int(row.id): int(row.document_count)
            for row in (
                await session.execute(
                    text("SELECT id, document_count FROM knowledge_index_versions")
                )
            ).all()
        }
    literal = vector_literal(embedder.embed_queries(["退货"])[0])

    async def query() -> tuple[int, int]:
        async with corpus.session() as session:
            rows = (
                await session.execute(
                    text(_SEARCH_SQL),
                    {
                        "row": 1,
                        "model": embedder.model_name,
                        "dims": 64,
                        "q": literal,
                        "limit": 1000,
                    },
                )
            ).all()
        versions = {int(row.version_id) for row in rows}
        assert len(versions) == 1, versions
        return versions.pop(), len(rows)

    seen: set[int] = set()
    for round_index in range(8):
        target = second.version_id if round_index % 2 == 0 else third.version_id
        outcomes = await asyncio.gather(*[query() for _ in range(200)], service.activate(target))
        for version, documents in outcomes[:-1]:  # type: ignore[misc]
            assert documents == expected[version], (version, documents)
            seen.add(version)
    assert len(seen) >= 2, seen
    assert await _active(corpus) == third.version_id


@pytest.mark.asyncio
async def test_gc_holds_pointer_transaction_until_chunks_are_collected(
    corpus: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(corpus, BigramEmbedder())
    first = await service.build()
    second = await service.build(activate=False)
    assert second.version_id is not None
    at_gc, release_gc = asyncio.Event(), asyncio.Event()
    original = AsyncSession.execute

    async def paused_execute(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(statement).startswith("DELETE FROM knowledge_chunks WHERE version_id IN"):
            at_gc.set()
            await release_gc.wait()
        return await original(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", paused_execute)
    task = asyncio.create_task(service.activate(second.version_id))
    try:
        await asyncio.wait_for(at_gc.wait(), timeout=10)
        # GC 尚未完成，另一个事务必须仍看到原指针，而非已提交的新指针。
        assert await _active(corpus) == first.version_id
    finally:
        release_gc.set()
        await task
    assert await _active(corpus) == second.version_id


@pytest.mark.asyncio
async def test_collected_version_cannot_be_reactivated(corpus: Database) -> None:
    service = _service(corpus, BigramEmbedder())
    versions = [(await service.build()).version_id for _ in range(3)]
    assert versions[0] is not None
    with pytest.raises(ValueError, match="incomplete"):
        await service.activate(versions[0])
    assert await _active(corpus) == versions[-1]
    assert (await _search(corpus, BigramEmbedder()).search("退货")).ranking


@pytest.mark.asyncio
async def test_activation_behind_corpus_stays_stale_even_on_first_switch(
    corpus: Database,
) -> None:
    """复审 F3：构建读完语料后又有保存——首次切换（此前没有指针行）同样保持陈旧，再建一轮后新鲜。"""

    service = _service(corpus, BigramEmbedder())
    built = await service.build(activate=False)
    assert built.version_id is not None
    async with corpus.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE knowledge_documents SET content = content || '（构建后修订）' WHERE id = "
                "(SELECT id FROM knowledge_documents ORDER BY source_path LIMIT 1)"
            )
        )
        await mark_corpus_changed(session)
    await service.activate(built.version_id)
    snapshot = await service.snapshot()
    assert snapshot.stale is True and snapshot.stale_reason == "CORPUS_CHANGED"
    await service.rebuild_until_fresh()
    assert (await service.snapshot()).stale is False


@pytest.mark.asyncio
async def test_unexpected_error_mid_build_does_not_leave_a_building_row(corpus: Database) -> None:
    """复审 F4：未预期异常照常抛出，但版本收尾为 FAILED，下一次构建不被「已有构建」挡掉。"""

    class Exploding(BigramEmbedder):
        def embed_passages(self, texts):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _service(corpus, Exploding()).build()
    assert (await _service(corpus, None).snapshot()).last_failure_reason == "BUILD_ABORTED"
    outcome = await _service(corpus, BigramEmbedder()).build()
    assert outcome.result is BuildResult.ACTIVATED


@pytest.mark.asyncio
async def test_gc_keeps_previous_active_and_newer_unactivated_versions(corpus: Database) -> None:
    """复审 F9：回收保留上一生效版本（可回滚）与更新的未激活版本，只删更早的。"""

    service = _service(corpus, BigramEmbedder())
    first = (await service.build()).version_id
    second = (await service.build(activate=False)).version_id
    third = (await service.build(activate=False)).version_id
    assert first is not None and second is not None and third is not None

    async def chunk_counts() -> dict[int, int]:
        async with corpus.session() as session:
            return {
                int(version): int(count)
                for version, count in (
                    await session.execute(
                        text(
                            "SELECT v.id, count(c.id) FROM knowledge_index_versions v "
                            "LEFT JOIN knowledge_chunks c ON c.version_id = v.id GROUP BY v.id"
                        )
                    )
                ).all()
            }

    await service.activate(second)
    counts = await chunk_counts()
    assert counts[first] > 0 and counts[second] > 0 and counts[third] > 0
    await service.activate(third)
    counts = await chunk_counts()
    assert counts[first] == 0 and counts[second] > 0 and counts[third] > 0


@pytest.mark.asyncio
async def test_failed_build_keeps_previous_and_marks_stale(corpus: Database) -> None:
    first = await _service(corpus, BigramEmbedder()).build()
    failed = await _service(corpus, FailingEmbedder()).build()
    assert failed.result is BuildResult.FAILED
    assert failed.failure_reason is IndexFailureReason.EMBEDDING_FAILED
    snapshot = await _service(corpus, None).snapshot()
    assert snapshot.active_version_id == first.version_id
    assert snapshot.stale is True and snapshot.last_failure_reason == "EMBEDDING_FAILED"
    result = await _search(corpus, BigramEmbedder()).search("退货退款的流程")
    assert result.status is IndexStatus.STALE and result.degraded_reason == INDEX_STALE_REASON
    async with corpus.session() as session:
        leftover = await session.scalar(
            text("SELECT count(*) FROM knowledge_chunks WHERE version_id = :id"),
            {"id": failed.version_id},
        )
    assert leftover == 0


@pytest.mark.asyncio
async def test_no_previous_version_falls_back_to_keyword_visibly(corpus: Database) -> None:
    failed = await _service(corpus, FailingEmbedder()).build()
    assert failed.result is BuildResult.FAILED and await _active(corpus) is None

    async with corpus.session() as session:
        out = await resolve_rule_search(
            "退货退款的流程是怎样的",
            retrieval=KnowledgeRetrieval(KnowledgeRepository(session)),
            vector=_search(corpus, BigramEmbedder()),
        )
    assert out.payload["matched"] is True  # 关键词仍然能答
    assert out.payload["retrieval"] == "KEYWORD_ONLY"
    assert out.payload["index_degraded_reason"] == INDEX_FALLBACK_REASON


@pytest.mark.asyncio
async def test_quality_regression_blocks_switch(corpus: Database) -> None:
    first = await _service(corpus, BigramEmbedder()).build()
    worse = await _service(corpus, RandomEmbedder()).build()
    assert worse.result is BuildResult.FAILED
    assert worse.failure_reason is IndexFailureReason.QUALITY_REGRESSION
    assert first.recall_at_5 is not None and worse.recall_at_5 is not None
    assert worse.recall_at_5 < first.recall_at_5 * 0.95
    assert await _active(corpus) == first.version_id


@pytest.mark.asyncio
async def test_model_mismatch_is_unavailable_not_garbage(corpus: Database) -> None:
    """换模型后新版本生效前，不拿新模型的查询向量去比旧向量。"""

    await _service(corpus, BigramEmbedder("model-a")).build()
    result = await _search(corpus, BigramEmbedder("model-b")).search("退货")
    assert result.status is IndexStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_only_one_build_at_a_time(corpus: Database) -> None:
    async with corpus.session() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO knowledge_index_versions (status, embedding_model) "
                "VALUES ('BUILDING', 'other-process')"
            )
        )
    outcome = await _service(corpus, BigramEmbedder()).build()
    assert outcome.result is BuildResult.ALREADY_BUILDING


@pytest.mark.asyncio
async def test_crashed_build_is_reclaimed_after_timeout(corpus: Database) -> None:
    async with corpus.session() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO knowledge_index_versions (status, embedding_model, started_at) "
                "VALUES ('BUILDING', 'crashed', now() - interval '2 hours')"
            )
        )
    outcome = await _service(corpus, BigramEmbedder()).build()
    assert outcome.result is BuildResult.ACTIVATED
    async with corpus.session() as session:
        reason = await session.scalar(
            text(
                "SELECT failure_reason FROM knowledge_index_versions "
                "WHERE embedding_model = 'crashed'"
            )
        )
    assert reason == "BUILD_TIMEOUT"


@pytest.mark.asyncio
async def test_corpus_change_marks_active_index_stale(corpus: Database) -> None:
    async with corpus.session() as session, session.begin():
        await mark_corpus_changed(session)  # 没有生效版本：无事可做，也不报错
    await _service(corpus, BigramEmbedder()).build()
    async with corpus.session() as session, session.begin():
        await mark_corpus_changed(session)
    snapshot = await _service(corpus, None).snapshot()
    assert snapshot.stale is True and snapshot.stale_reason == "CORPUS_CHANGED"
    await _service(corpus, BigramEmbedder()).build()
    assert (await _service(corpus, None).snapshot()).stale is False


@pytest.mark.asyncio
async def test_old_versions_lose_chunks_but_keep_history(corpus: Database) -> None:
    ids = [(await _service(corpus, BigramEmbedder()).build()).version_id for _ in range(3)]
    async with corpus.session() as session:
        counts = dict(
            (
                await session.execute(
                    text(
                        "SELECT v.id, count(c.id) FROM knowledge_index_versions v "
                        "LEFT JOIN knowledge_chunks c ON c.version_id = v.id GROUP BY v.id"
                    )
                )
            ).all()
        )
    assert counts[ids[0]] == 0  # 最早的版本只留版本行
    assert counts[ids[1]] > 0 and counts[ids[2]] > 0  # 生效版本与上一版保留分块


@pytest.mark.asyncio
async def test_empty_corpus_fails_without_activating(
    db_session: AsyncSession, integration_database: Database
) -> None:
    outcome = await _service(integration_database, BigramEmbedder()).build()
    assert outcome.failure_reason is IndexFailureReason.EMPTY_CORPUS
    assert await _active(integration_database) is None


@pytest.mark.asyncio
async def test_needs_build_tracks_model_and_corpus(corpus: Database) -> None:
    service = _service(corpus, BigramEmbedder())
    assert await service.needs_build() is True
    await service.build()
    assert await service.needs_build() is False
    assert await _service(corpus, BigramEmbedder("other-model")).needs_build() is True
    async with corpus.session() as session, session.begin():
        await session.execute(
            text(
                "UPDATE knowledge_documents SET content = content || '（修订）' WHERE id = "
                "(SELECT id FROM knowledge_documents ORDER BY source_path LIMIT 1)"
            )
        )
    assert await service.needs_build() is True
    assert await _service(corpus, None).needs_build() is False  # 未配置模型：不构建
