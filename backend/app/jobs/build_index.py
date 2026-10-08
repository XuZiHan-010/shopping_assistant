"""手动构建并切换知识索引新版本（N4-C，PRD §7.6）。

日常不需要手动运行：backend 启动后会在后台检查并重建（`app.main._warm_up_and_index`），
知识后台保存后也会触发重建。本命令供运维排障与 N5 Cron（`n5-budget-ops-and-railway`）使用。

- 先补齐镜像内团队知识种子（与启动时同一 insert-if-absent 语义），新库也有语料；
- 只在 `needs_build()` 为真时构建：生效版本缺失、陈旧、换了模型或语料已变；
- 构建失败时旧版本继续服务并标陈旧，无旧版本时检索降级为关键词并如实标注，两者在知识后台可见；
  日志只有稳定原因码，不含正文。

运行：`python -m app.jobs.build_index`。本地推理，不调用 LLM。
"""

from __future__ import annotations

import asyncio

import structlog

from app.core.config import Settings, get_settings
from app.db.session import Database
from app.knowledge.embedding import build_embedder
from app.knowledge.index_versions import BuildOutcome, KnowledgeIndexService
from app.knowledge.wiki_seed import seed_wiki_documents

logger = structlog.get_logger(__name__)


def index_service(database: Database, settings: Settings) -> KnowledgeIndexService:
    embedder = build_embedder(
        settings.embedding_model,
        cache_dir=settings.embedding_cache_dir,
        threads=settings.embedding_threads,
    )
    return KnowledgeIndexService(database, embedder)


async def build_if_needed(database: Database, settings: Settings) -> BuildOutcome | None:
    # 与后台保存同一入口：构建期间又有保存时再建一轮（复审 F3）。
    return await index_service(database, settings).rebuild_until_fresh()


async def _main() -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        await database.connect_with_retry()
        await seed_wiki_documents(database)
        outcome = await build_if_needed(database, settings)
        if outcome is None:
            logger.info("knowledge_index_up_to_date", model=settings.embedding_model)
        else:
            logger.info(
                "knowledge_index_build_finished",
                result=outcome.result.value,
                version_id=outcome.version_id,
                failure_reason=outcome.failure_reason.value if outcome.failure_reason else None,
                recall_at_5=outcome.recall_at_5,
            )
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
