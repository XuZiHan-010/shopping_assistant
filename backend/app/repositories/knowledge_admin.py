"""知识库后台的专用读写仓储。

检索仓储只暴露 ACTIVE 文档的读取接口；本模块为管理员维护场景提供按
虚拟路径查询、写入和批量迁移，避免让检索侧获得写权限。
"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeDocument


class KnowledgeAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_paths(self, prefix: str) -> list[KnowledgeDocument]:
        statement = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.source_path.startswith(prefix))
            .order_by(KnowledgeDocument.source_path)
        )
        result = await self._session.execute(statement)
        return list(result.scalars())

    async def get_by_path(self, virtual_path: str) -> KnowledgeDocument | None:
        statement = select(KnowledgeDocument).where(KnowledgeDocument.source_path == virtual_path)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def find_case_insensitive(self, parent: str, name: str) -> KnowledgeDocument | None:
        path = f"{parent}/{name}".lower()
        statement = select(KnowledgeDocument).where(
            func.lower(KnowledgeDocument.source_path) == path
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        virtual_path: str,
        category: str,
        title: str,
        content: str,
        is_complete: bool = True,
    ) -> KnowledgeDocument:
        document = KnowledgeDocument(
            source_path=virtual_path,
            category=category,
            title=title,
            content=content,
            source="ADMIN",
            is_complete=is_complete,
            status="ACTIVE",
        )
        self._session.add(document)
        return document

    async def update_content(self, document: KnowledgeDocument, content: str) -> KnowledgeDocument:
        document.content = content
        document.version += 1
        return document

    async def update_content_if_current(
        self, document_id: object, expected_content: str, content: str
    ) -> KnowledgeDocument | None:
        """以读取时正文为条件更新，避免两个相同 ETag 的写入互相覆盖。"""

        statement = (
            update(KnowledgeDocument)
            .where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.content == expected_content,
            )
            .values(
                content=content,
                version=KnowledgeDocument.version + 1,
            )
            .returning(KnowledgeDocument)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def delete(self, document: KnowledgeDocument) -> None:
        await self._session.delete(document)

    async def move_prefix(self, old_prefix: str, new_prefix: str) -> int:
        statement = (
            update(KnowledgeDocument)
            .where(KnowledgeDocument.source_path.startswith(old_prefix))
            .values(source_path=func.replace(KnowledgeDocument.source_path, old_prefix, new_prefix))
            .returning(KnowledgeDocument.id)
        )
        result = await self._session.execute(statement)
        return len(result.scalars().all())

    async def count_under(self, prefix: str) -> int:
        statement = (
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.source_path.startswith(prefix))
        )
        return int(await self._session.scalar(statement) or 0)
