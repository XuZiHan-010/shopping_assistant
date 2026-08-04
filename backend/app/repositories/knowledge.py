"""团队知识文档仓储。

团队知识对所有商家一致，不含商家数据，因此此处刻意不按 ``merchant_id``
过滤。商家级记忆属于 P1 的独立表，届时必须实施商家隔离。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDocument


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> list[KnowledgeDocument]:
        statement = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.status == "ACTIVE")
            .order_by(KnowledgeDocument.source_path)
        )
        result = await self._session.execute(statement)
        return list(result.scalars())

    async def upsert_by_source_path(
        self,
        *,
        source_path: str,
        category: str,
        title: str,
        content: str,
        source: str,
        is_complete: bool,
    ) -> KnowledgeDocument:
        """按来源路径幂等写入，供可重复执行的 Wiki 导入调用。"""

        existing = await self._session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.source_path == source_path)
        )
        if existing is None:
            document = KnowledgeDocument(
                source_path=source_path,
                category=category,
                title=title,
                content=content,
                source=source,
                is_complete=is_complete,
                status="ACTIVE",
            )
            self._session.add(document)
            return document

        existing.category = category
        existing.title = title
        existing.content = content
        existing.source = source
        existing.is_complete = is_complete
        existing.version += 1
        return existing
