"""知识索引版本状态机与向量查询（PRD A7、M12、§7.6，契约 §6.14）。

```text
构建中 → 验证中 → 已就绪 →（原子切换）→ 生效
构建中 / 验证中 → 失败 → 继续使用上一生效版本并标记陈旧
无可用旧版本 → 降级为关键词检索并显式标注
```

三条不变量与它们的落点：

1. **切换原子**：生效 = `knowledge_index_state` 单行指针；`activate()` 在一个事务里只改这一行。
   查询用**一条** SQL 同时读指针与分块，READ COMMITTED 下单条语句只看到一个快照，
   所以一次检索要么全是旧版本、要么全是新版本。分块只按版本插入，从不 `UPDATE`；
2. **失败保可用**：构建或验证失败时只把新版本置 FAILED 并给指针打上陈旧标记，不碰生效版本；
3. **降级可见**：`VectorIndexSearch` 把「无可用索引 / 陈旧」作为状态返回，
   由 `search_rules` 写进工具结果，Chat 服务据此在 `analysis_sources` 的 KNOWLEDGE 项上
   如实标注（R7）。

同一时刻只允许一个版本处于构建/验证中：迁移里的部分唯一索引由数据库强制；
构建进程崩溃留下的 BUILDING 行超过 `build_timeout` 后，下一次构建开始前将其置为 FAILED。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import anyio
import yaml
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.embedding import Embedder, EmbeddingUnavailableError
from app.knowledge.versioning import document_version
from app.models.knowledge_index import INDEX_STATE_ROW_ID

logger = logging.getLogger(__name__)

#: 验证探针：与 E5 评测集同一份文件（见文件头注释）。
PROBES_PATH: Final = Path(__file__).parent / "probes" / "n4_e5_rag.yaml"
#: 新版本 Recall@5 低于上一生效版本的这个比例即判失败，不切换（计划 Task 2）。
MIN_RECALL_RATIO: Final = 0.95
#: 分块目标长度（字符）。语料单篇 ≤2k 字，按段落累加到约 400 字切一块，每块前缀标题。
CHUNK_TARGET_CHARS: Final = 400
#: 构建进程崩溃后，超过这个时长的 BUILDING/VALIDATING 行在下一次构建前被回收为 FAILED。
DEFAULT_BUILD_TIMEOUT: Final = timedelta(minutes=30)


class IndexFailureReason(StrEnum):
    EMBEDDING_UNAVAILABLE = "EMBEDDING_UNAVAILABLE"  # 未配置模型或模型加载失败
    EMBEDDING_FAILED = "EMBEDDING_FAILED"  # 推理过程出错
    QUALITY_REGRESSION = "QUALITY_REGRESSION"  # Recall@5 低于上一生效版本 95%
    EMPTY_CORPUS = "EMPTY_CORPUS"  # 没有任何生效文档
    BUILD_TIMEOUT = "BUILD_TIMEOUT"  # 构建进程中断后被回收
    BUILD_ABORTED = "BUILD_ABORTED"  # 构建中途出现未预期异常或被取消（如关机）
    STORAGE_FAILED = "STORAGE_FAILED"  # 写分块或改状态时数据库出错


class StaleReason(StrEnum):
    BUILD_FAILED = "BUILD_FAILED"  # 最近一次构建失败，生效版本落后于语料
    CORPUS_CHANGED = "CORPUS_CHANGED"  # 文档已保存/删除，新版本尚未生效


class IndexStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class BuildResult(StrEnum):
    ACTIVATED = "ACTIVATED"
    READY = "READY"  # 通过验证但调用方要求暂不切换
    FAILED = "FAILED"
    ALREADY_BUILDING = "ALREADY_BUILDING"


#: 知识来源的单来源降级原因码（`analysis_sources[*].degraded_reason`）。
INDEX_STALE_REASON: Final = "INDEX_STALE"
INDEX_FALLBACK_REASON: Final = "INDEX_UNAVAILABLE_KEYWORD_FALLBACK"


@dataclass(frozen=True)
class Probe:
    query: str
    expected: tuple[str, ...]


@dataclass(frozen=True)
class Chunk:
    source_path: str
    chunk_index: int
    content: str


@dataclass(frozen=True)
class BuildOutcome:
    result: BuildResult
    version_id: int | None
    failure_reason: IndexFailureReason | None = None
    recall_at_5: float | None = None


@dataclass(frozen=True)
class IndexSnapshot:
    """知识后台展示用的索引状态；不含分块正文与向量。"""

    active_version_id: int | None
    embedding_model: str | None
    configured_model: str | None
    stale: bool
    stale_reason: str | None
    building: bool
    last_failure_reason: str | None

    @property
    def hybrid(self) -> bool:
        return self.active_version_id is not None and self.embedding_model == self.configured_model


@dataclass(frozen=True)
class VectorSearchResult:
    status: IndexStatus
    #: 按相似度降序的 `(source_path, 最高块相似度)`，已按最低相似度过滤。
    ranking: tuple[tuple[str, float], ...]
    version_id: int | None

    @property
    def degraded_reason(self) -> str | None:
        if self.status is IndexStatus.UNAVAILABLE:
            return INDEX_FALLBACK_REASON
        if self.status is IndexStatus.STALE:
            return INDEX_STALE_REASON
        return None


_UNAVAILABLE: Final = VectorSearchResult(IndexStatus.UNAVAILABLE, (), None)


def load_probes(path: Path = PROBES_PATH) -> tuple[Probe, ...]:
    """只取可回答用例；「应当找不到」的用例与 Recall 无关。"""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(
        Probe(query=str(case["query"]), expected=tuple(str(p) for p in case["expected"]))
        for case in raw
        if case["expected"]
    )


def chunk_document(source_path: str, title: str, content: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    buffer = ""
    for paragraph in (p.strip() for p in content.split("\n\n")):
        if not paragraph:
            continue
        if buffer and len(buffer) + len(paragraph) > CHUNK_TARGET_CHARS:
            chunks.append(Chunk(source_path, len(chunks), f"{title}\n{buffer}"))
            buffer = ""
        buffer = f"{buffer}\n{paragraph}" if buffer else paragraph
    if buffer or not chunks:
        chunks.append(Chunk(source_path, len(chunks), f"{title}\n{buffer}"))
    return chunks


def corpus_fingerprint(documents: Sequence[tuple[str, str, str]]) -> str:
    signature = "\n".join(
        f"{path}:{document_version(title + chr(10) + content)}"
        for path, title, content in sorted(documents)
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def vector_literal(vector: Sequence[float]) -> str:
    if not vector or not all(math.isfinite(x) for x in vector):
        raise EmbeddingUnavailableError("embedding contains no or non-finite values")
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def _normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def probe_recall_at_5(
    probes: Sequence[Probe],
    chunks: Sequence[Chunk],
    chunk_vectors: Sequence[Sequence[float]],
    query_vectors: Sequence[Sequence[float]],
) -> float | None:
    """纯向量 Recall@5；只计期望文档全部仍在语料里的探针（管理员删掉的文档不算回退）。"""

    present = {chunk.source_path for chunk in chunks}
    normalized = [_normalize(v) for v in chunk_vectors]
    scores: list[float] = []
    for probe, query in zip(probes, query_vectors, strict=True):
        if not set(probe.expected) <= present:
            continue
        q = _normalize(query)
        best: dict[str, float] = {}
        for chunk, vector in zip(chunks, normalized, strict=True):
            similarity = sum(a * b for a, b in zip(q, vector, strict=True))
            best[chunk.source_path] = max(best.get(chunk.source_path, -1.0), similarity)
        top = {path for path, _ in sorted(best.items(), key=lambda kv: -kv[1])[:5]}
        scores.append(sum(path in top for path in probe.expected) / len(probe.expected))
    return round(sum(scores) / len(scores), 4) if scores else None


async def mark_corpus_changed(session: AsyncSession) -> None:
    """文档保存/删除时与写入同一事务调用：有生效版本才标陈旧（无版本时本来就是降级）。

    先确保指针行存在（复审 F3）：没有这一行时 UPDATE 不加任何锁，保存若恰好在首次切换读完语料之后
    提交，切换会把落后的版本报成新鲜。行存在后，保存与切换在这一行上串行，陈旧标记不会丢。
    """

    await session.execute(
        text("INSERT INTO knowledge_index_state (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"),
        {"id": INDEX_STATE_ROW_ID},
    )
    await session.execute(
        text(
            "UPDATE knowledge_index_state SET stale = true, stale_reason = :reason, "
            "updated_at = now() WHERE id = :id AND active_version_id IS NOT NULL"
        ),
        {"reason": StaleReason.CORPUS_CHANGED.value, "id": INDEX_STATE_ROW_ID},
    )


async def _active_documents(session: AsyncSession) -> list[tuple[str, str, str]]:
    rows = (
        await session.execute(
            text(
                "SELECT source_path, title, content FROM knowledge_documents "
                "WHERE status = 'ACTIVE' ORDER BY source_path"
            )
        )
    ).all()
    return [(str(r.source_path), str(r.title), str(r.content)) for r in rows]


class KnowledgeIndexService:
    def __init__(
        self,
        database: Database,
        embedder: Embedder | None,
        *,
        probes: Sequence[Probe] | None = None,
        min_recall_ratio: float = MIN_RECALL_RATIO,
        build_timeout: timedelta = DEFAULT_BUILD_TIMEOUT,
    ) -> None:
        self._database = database
        self._embedder = embedder
        self._probes = tuple(probes) if probes is not None else load_probes()
        self._min_recall_ratio = min_recall_ratio
        self._build_timeout = build_timeout

    async def needs_build(self) -> bool:
        """生效版本缺失、陈旧、模型不同或语料指纹已变时才需要重建（部署与后台触发都先问这一句）。"""

        if self._embedder is None:
            return False
        async with self._database.session() as session:
            active = (
                await session.execute(
                    text(
                        "SELECT s.stale, v.embedding_model, v.corpus_fingerprint "
                        "FROM knowledge_index_state s "
                        "JOIN knowledge_index_versions v ON v.id = s.active_version_id "
                        "WHERE s.id = :row"
                    ),
                    {"row": INDEX_STATE_ROW_ID},
                )
            ).first()
            documents = await _active_documents(session)
        if active is None:
            return True
        current = corpus_fingerprint(documents)
        return bool(
            active.stale
            or active.embedding_model != self._embedder.model_name
            or active.corpus_fingerprint != current
        )

    async def rebuild_until_fresh(self, *, max_rounds: int = 3) -> BuildOutcome | None:
        """知识后台保存后调用：构建期间又有保存时再建一轮，最多 `max_rounds` 轮。

        另一进程正在构建时直接返回——它结束后会自己复查语料。失败也返回，
        不在失败上无限重试（陈旧标记与失败原因在知识后台可见）。
        """

        outcome: BuildOutcome | None = None
        for _ in range(max_rounds):
            if not await self.needs_build():
                return outcome
            outcome = await self.build()
            if outcome.result is not BuildResult.ACTIVATED:
                return outcome
        return outcome

    async def build(self, *, activate: bool = True) -> BuildOutcome:
        model_name = self._embedder.model_name if self._embedder is not None else "none"
        version_id = await self._start(model_name)
        if version_id is None:
            return BuildOutcome(BuildResult.ALREADY_BUILDING, None)
        try:
            return await self._build(version_id, activate=activate)
        except BaseException:
            # 未预期异常或取消（关机时取消预热任务）不能留下 BUILDING 行，否则 30 分钟内的重建都会被
            # 当作「已有构建」挡掉（复审 F4）。收尾写入不受取消影响，原异常照常抛出。
            await asyncio.shield(self._abort(version_id))
            raise

    async def _build(self, version_id: int, *, activate: bool) -> BuildOutcome:
        if self._embedder is None:
            return await self._fail(version_id, IndexFailureReason.EMBEDDING_UNAVAILABLE)

        async with self._database.session() as session:
            documents = await _active_documents(session)
        if not documents:
            return await self._fail(version_id, IndexFailureReason.EMPTY_CORPUS)
        chunks = [c for path, title, body in documents for c in chunk_document(path, title, body)]

        embedder = self._embedder
        try:
            chunk_vectors = await anyio.to_thread.run_sync(
                embedder.embed_passages, [c.content for c in chunks]
            )
            literals = [vector_literal(v) for v in chunk_vectors]
        except EmbeddingUnavailableError:
            return await self._fail(version_id, IndexFailureReason.EMBEDDING_FAILED)
        if len(chunk_vectors) != len(chunks) or len({len(v) for v in chunk_vectors}) != 1:
            return await self._fail(version_id, IndexFailureReason.EMBEDDING_FAILED)

        try:
            await self._store(version_id, chunks, literals, documents, len(chunk_vectors[0]))
        except SQLAlchemyError:
            return await self._fail(version_id, IndexFailureReason.STORAGE_FAILED)

        try:
            query_vectors = await anyio.to_thread.run_sync(
                embedder.embed_queries, [p.query for p in self._probes]
            )
        except EmbeddingUnavailableError:
            return await self._fail(version_id, IndexFailureReason.EMBEDDING_FAILED)
        recall = await anyio.to_thread.run_sync(
            probe_recall_at_5, self._probes, chunks, chunk_vectors, query_vectors
        )
        baseline = await self._active_recall()
        regressed = (
            recall is not None
            and baseline is not None
            and recall < baseline * self._min_recall_ratio
        )
        if regressed:
            return await self._fail(
                version_id, IndexFailureReason.QUALITY_REGRESSION, recall=recall, baseline=baseline
            )

        async with self._database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE knowledge_index_versions SET status = 'READY', recall_at_5 = :recall, "
                    "baseline_recall_at_5 = :baseline, finished_at = now() WHERE id = :id"
                ),
                {"recall": recall, "baseline": baseline, "id": version_id},
            )
        if not activate:
            return BuildOutcome(BuildResult.READY, version_id, recall_at_5=recall)
        await self.activate(version_id)
        return BuildOutcome(BuildResult.ACTIVATED, version_id, recall_at_5=recall)

    async def activate(self, version_id: int) -> None:
        """原子切换：持有指针锁的同一事务内切换并回收，防止交错回收生效版本。

        构建读语料之后、切换之前若又有保存，这个版本已经落后：切换照做（它仍比旧版本新），
        但保持 `CORPUS_CHANGED` 陈旧，由 `rebuild_until_fresh()` 再建一轮。先锁指针行再读语料——
        后台保存在同一事务里写文档并更新指针行，锁顺序保证它的陈旧标记不会被这次切换覆盖。
        """

        async with self._database.session() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO knowledge_index_state (id) VALUES (:row) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {"row": INDEX_STATE_ROW_ID},
            )
            previous = await session.scalar(
                text(
                    "SELECT active_version_id FROM knowledge_index_state WHERE id = :row FOR UPDATE"
                ),
                {"row": INDEX_STATE_ROW_ID},
            )
            version = (
                await session.execute(
                    text(
                        "SELECT status, corpus_fingerprint, chunk_count, document_count "
                        "FROM knowledge_index_versions "
                        "WHERE id = :id FOR UPDATE"
                    ),
                    {"id": version_id},
                )
            ).first()
            if version is None or version.status != "READY":
                raise ValueError(f"index version {version_id} is not READY")
            counts = (
                await session.execute(
                    text(
                        "SELECT count(*) AS chunks, count(DISTINCT source_path) AS documents "
                        "FROM knowledge_chunks WHERE version_id = :id"
                    ),
                    {"id": version_id},
                )
            ).one()
            if (
                counts.chunks != version.chunk_count
                or counts.documents != version.document_count
                or counts.chunks == 0
            ):
                raise ValueError(f"index version {version_id} has incomplete chunks")
            current = corpus_fingerprint(await _active_documents(session))
            behind = version.corpus_fingerprint != current
            await session.execute(
                text(
                    "UPDATE knowledge_index_state SET active_version_id = :id, stale = :stale, "
                    "stale_reason = :reason, updated_at = now() WHERE id = :row"
                ),
                {
                    "row": INDEX_STATE_ROW_ID,
                    "id": version_id,
                    "stale": behind,
                    "reason": StaleReason.CORPUS_CHANGED.value if behind else None,
                },
            )
            # 回收：保留新生效版本、上一生效版本（可回滚），以及比新生效版本更新、
            # 尚未激活的 READY 版本；只删更早且不是上一生效版本的分块
            # （复审 F9：按「最新 N 个」删会误删上一生效版本）。
            await session.execute(
                text(
                    "DELETE FROM knowledge_chunks WHERE version_id IN ("
                    "  SELECT id FROM knowledge_index_versions WHERE status = 'READY' "
                    "  AND id < :active AND id <> :previous)"
                ),
                {"active": version_id, "previous": previous if previous is not None else -1},
            )

    async def snapshot(self) -> IndexSnapshot:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT s.active_version_id, v.embedding_model, s.stale, s.stale_reason "
                        "FROM knowledge_index_state s "
                        "LEFT JOIN knowledge_index_versions v ON v.id = s.active_version_id "
                        "WHERE s.id = :row"
                    ),
                    {"row": INDEX_STATE_ROW_ID},
                )
            ).first()
            building = bool(
                await session.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM knowledge_index_versions "
                        "WHERE status IN ('BUILDING', 'VALIDATING'))"
                    )
                )
            )
            last_failure = await session.scalar(
                text(
                    "SELECT failure_reason FROM knowledge_index_versions WHERE status = 'FAILED' "
                    "AND id > COALESCE((SELECT active_version_id FROM knowledge_index_state "
                    "WHERE id = :row), 0) ORDER BY id DESC LIMIT 1"
                ),
                {"row": INDEX_STATE_ROW_ID},
            )
        return IndexSnapshot(
            active_version_id=row.active_version_id if row else None,
            embedding_model=row.embedding_model if row else None,
            configured_model=self._embedder.model_name if self._embedder is not None else None,
            stale=bool(row.stale) if row else False,
            stale_reason=row.stale_reason if row else None,
            building=building,
            last_failure_reason=last_failure,
        )

    async def _start(self, model_name: str) -> int | None:
        async with self._database.session() as session:
            try:
                async with session.begin():
                    await session.execute(
                        text(
                            "UPDATE knowledge_index_versions SET status = 'FAILED', "
                            "failure_reason = :reason, finished_at = now() "
                            "WHERE status IN ('BUILDING', 'VALIDATING') "
                            "AND started_at < now() - make_interval(secs => :timeout)"
                        ),
                        {
                            "reason": IndexFailureReason.BUILD_TIMEOUT.value,
                            "timeout": self._build_timeout.total_seconds(),
                        },
                    )
                    version_id = await session.scalar(
                        text(
                            "INSERT INTO knowledge_index_versions (status, embedding_model) "
                            "VALUES ('BUILDING', :model) RETURNING id"
                        ),
                        {"model": model_name},
                    )
            except IntegrityError:
                return None
        return int(version_id) if version_id is not None else None

    async def _store(
        self,
        version_id: int,
        chunks: Sequence[Chunk],
        literals: Sequence[str],
        documents: Sequence[tuple[str, str, str]],
        dimensions: int,
    ) -> None:
        async with self._database.session() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(id, version_id, source_path, chunk_index, content, embedding) "
                    "VALUES (:id, :version, :path, :index, :content, CAST(:embedding AS vector))"
                ),
                [
                    {
                        "id": uuid4(),
                        "version": version_id,
                        "path": chunk.source_path,
                        "index": chunk.chunk_index,
                        "content": chunk.content,
                        "embedding": literal,
                    }
                    for chunk, literal in zip(chunks, literals, strict=True)
                ],
            )
            await session.execute(
                text(
                    "UPDATE knowledge_index_versions SET status = 'VALIDATING', "
                    "dimensions = :dims, corpus_fingerprint = :fp, document_count = :docs, "
                    "chunk_count = :chunks WHERE id = :id"
                ),
                {
                    "dims": dimensions,
                    "fp": corpus_fingerprint(documents),
                    "docs": len(documents),
                    "chunks": len(chunks),
                    "id": version_id,
                },
            )

    async def _active_recall(self) -> float | None:
        async with self._database.session() as session:
            value = await session.scalar(
                text(
                    "SELECT v.recall_at_5 FROM knowledge_index_state s "
                    "JOIN knowledge_index_versions v ON v.id = s.active_version_id "
                    "WHERE s.id = :row"
                ),
                {"row": INDEX_STATE_ROW_ID},
            )
        return float(value) if value is not None else None

    async def _abort(self, version_id: int) -> None:
        """只收尾仍在构建/验证中的版本；已 READY 的不动。收尾本身出错不掩盖原异常。"""

        try:
            async with self._database.session() as session, session.begin():
                aborted = await session.scalar(
                    text(
                        "UPDATE knowledge_index_versions SET status = 'FAILED', "
                        "failure_reason = :reason, finished_at = now() "
                        "WHERE id = :id AND status IN ('BUILDING', 'VALIDATING') RETURNING id"
                    ),
                    {"reason": IndexFailureReason.BUILD_ABORTED.value, "id": version_id},
                )
                if aborted is None:
                    return
                await session.execute(
                    text("DELETE FROM knowledge_chunks WHERE version_id = :id"), {"id": version_id}
                )
                await session.execute(
                    text(
                        "UPDATE knowledge_index_state SET stale = true, stale_reason = :stale, "
                        "updated_at = now() WHERE id = :row AND active_version_id IS NOT NULL"
                    ),
                    {"stale": StaleReason.BUILD_FAILED.value, "row": INDEX_STATE_ROW_ID},
                )
        except SQLAlchemyError:
            logger.warning("knowledge_index_abort_cleanup_failed version_id=%s", version_id)

    async def _fail(
        self,
        version_id: int,
        reason: IndexFailureReason,
        *,
        recall: float | None = None,
        baseline: float | None = None,
    ) -> BuildOutcome:
        async with self._database.session() as session, session.begin():
            await session.execute(
                text("DELETE FROM knowledge_chunks WHERE version_id = :id"), {"id": version_id}
            )
            await session.execute(
                text(
                    "UPDATE knowledge_index_versions SET status = 'FAILED', "
                    "failure_reason = :reason, "
                    "recall_at_5 = :recall, baseline_recall_at_5 = :baseline, finished_at = now() "
                    "WHERE id = :id"
                ),
                {"reason": reason.value, "recall": recall, "baseline": baseline, "id": version_id},
            )
            await session.execute(
                text(
                    "UPDATE knowledge_index_state SET stale = true, stale_reason = :stale, "
                    "updated_at = now() WHERE id = :row AND active_version_id IS NOT NULL"
                ),
                {"stale": StaleReason.BUILD_FAILED.value, "row": INDEX_STATE_ROW_ID},
            )
        return BuildOutcome(BuildResult.FAILED, version_id, reason, recall)


class VectorIndexSearch:
    """查询期向量召回：一条 SQL 读指针 + 分块，保证一次检索只看到一个版本。"""

    def __init__(
        self,
        database: Database,
        embedder: Embedder | None,
        *,
        min_similarity: float,
        limit: int = 10,
    ) -> None:
        self._database = database
        self._embedder = embedder
        self._min_similarity = min_similarity
        self._limit = limit

    async def search(self, query: str) -> VectorSearchResult:
        if self._embedder is None or not query.strip():
            return _UNAVAILABLE
        try:
            vectors = await anyio.to_thread.run_sync(self._embedder.embed_queries, [query])
            literal = vector_literal(vectors[0])
        except (EmbeddingUnavailableError, IndexError):
            return _UNAVAILABLE
        try:
            async with self._database.session() as session:
                rows = (
                    await session.execute(
                        text(_SEARCH_SQL),
                        {
                            "row": INDEX_STATE_ROW_ID,
                            "model": self._embedder.model_name,
                            "dims": len(vectors[0]),
                            "q": literal,
                            "limit": self._limit,
                        },
                    )
                ).all()
        except SQLAlchemyError:
            return _UNAVAILABLE
        return _to_result(rows, self._min_similarity)


#: 指针、版本与分块在同一条语句里连接：READ COMMITTED 下单条语句只有一个快照。
#: 模型与维度不一致的版本视同不可用（换模型后、新版本生效前，不拿新模型的查询向量去比旧向量）。
_SEARCH_SQL: Final = """
SELECT v.id AS version_id, s.stale AS stale, c.source_path AS source_path,
       MAX(1 - (c.embedding <=> CAST(:q AS vector))) AS similarity
FROM knowledge_index_state s
JOIN knowledge_index_versions v
  ON v.id = s.active_version_id AND v.embedding_model = :model AND v.dimensions = :dims
JOIN knowledge_chunks c ON c.version_id = v.id
WHERE s.id = :row
GROUP BY v.id, s.stale, c.source_path
ORDER BY similarity DESC
LIMIT :limit
"""


def _to_result(rows: Sequence[Any], min_similarity: float) -> VectorSearchResult:
    if not rows:
        return _UNAVAILABLE
    status = IndexStatus.STALE if rows[0].stale else IndexStatus.FRESH
    ranking = tuple(
        (str(row.source_path), float(row.similarity))
        for row in rows
        if float(row.similarity) >= min_similarity
    )
    return VectorSearchResult(status, ranking, int(rows[0].version_id))
