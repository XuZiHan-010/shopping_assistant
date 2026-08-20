"""知识库后台的目录树装配服务。"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, KnowledgeAdminError
from app.knowledge.path_policy import (
    BUSINESS_SECTIONS,
    KnowledgePathError,
    ResolvedPath,
    resolve_readable,
    resolve_writable_document,
    validate_domain_name,
)
from app.knowledge.versioning import directory_version, document_version
from app.models.knowledge import KnowledgeDocument, MerchantMemory
from app.repositories.knowledge_admin import KnowledgeAdminRepository
from app.schemas.knowledge import (
    KnowledgeDocumentResponse,
    KnowledgeTreeNode,
    KnowledgeTreeResponse,
)


class KnowledgeAdminService:
    """由数据库文档和只读商家记忆推导维护后台目录树。"""

    def __init__(self, session: AsyncSession, *, max_document_bytes: int = 262_144) -> None:
        self._session = session
        self._documents = KnowledgeAdminRepository(session)
        self._max_document_bytes = max_document_bytes

    async def tree(self) -> KnowledgeTreeResponse:
        index_documents = await self._documents.list_paths("index/")
        business_documents = await self._documents.list_paths("业务/")
        memory_rows = await self._list_active_memories()
        return KnowledgeTreeResponse(
            roots=[
                self._index_root(index_documents),
                self._business_root(business_documents),
                self._memory_root(memory_rows),
            ]
        )

    async def get_document(self, raw_path: str) -> KnowledgeDocumentResponse:
        resolved = self._resolve_readable(raw_path)
        if not resolved.virtual_path.endswith(".md"):
            raise KnowledgeAdminError(ErrorCode.INVALID_FILE_TYPE, "只允许读取 Markdown 文档", 400)
        if resolved.read_only:
            return await self._get_memory_document(resolved.virtual_path)
        document = await self._documents.get_by_path(resolved.virtual_path)
        if document is None:
            raise KnowledgeAdminError(ErrorCode.WIKI_NODE_NOT_FOUND, "知识文档不存在", 404)
        return self._document_response(resolved, document.content)

    async def create_document(self, raw_path: str, content: str) -> KnowledgeDocumentResponse:
        resolved = self._resolve_writable(raw_path)
        self._validate_content(content)
        existing = await self._documents.get_by_path(resolved.virtual_path)
        parent, name = resolved.virtual_path.rsplit("/", maxsplit=1)
        conflicting = await self._documents.find_case_insensitive(parent, name)
        if existing is not None or conflicting is not None:
            raise KnowledgeAdminError(ErrorCode.WIKI_NODE_EXISTS, "同名文档已存在", 409)
        if resolved.virtual_path.startswith("业务/"):
            domain = resolved.virtual_path.split("/")[1]
            if await self._documents.count_under(f"业务/{domain}/") == 0:
                raise KnowledgeAdminError(
                    ErrorCode.INVALID_WIKI_PARENT, "目标业务域或固定板块不存在", 400
                )
        document = await self._documents.create(
            virtual_path=resolved.virtual_path,
            category="UNKNOWN",
            title=name.removesuffix(".md"),
            content=content,
        )
        await self._session.flush()
        return self._document_response(resolved, document.content)

    async def update_document(
        self, raw_path: str, content: str, if_match: str | None
    ) -> KnowledgeDocumentResponse:
        resolved = self._resolve_writable(raw_path)
        document = await self._require_maintained_document(resolved.virtual_path)
        self._require_version(if_match, document.content)
        self._validate_content(content)
        updated = await self._documents.update_content_if_current(
            document.id, document.content, content
        )
        if updated is None:
            raise KnowledgeAdminError(
                ErrorCode.WIKI_VERSION_CONFLICT, "文档已被其他维护者更新", 412
            )
        await self._session.flush()
        return self._document_response(resolved, updated.content)

    async def delete_document(self, raw_path: str, if_match: str | None) -> None:
        resolved = self._resolve_writable(raw_path)
        document = await self._require_maintained_document(resolved.virtual_path)
        self._require_version(if_match, document.content)
        await self._documents.delete(document)
        await self._session.flush()

    async def create_business_domain(self, raw_name: str) -> KnowledgeTreeNode:
        name = self._validate_domain_name(raw_name)
        if await self._domain_exists(name):
            raise KnowledgeAdminError(ErrorCode.WIKI_NODE_EXISTS, "同名业务域已存在", 409)
        for section in BUSINESS_SECTIONS:
            await self._documents.create(
                virtual_path=f"业务/{name}/{section}/待补充.md",
                category="UNKNOWN",
                title="待补充",
                content=f"# {name}／{section}\n\n资料尚未完整，请由管理员补充。",
                is_complete=False,
            )
        await self._session.flush()
        return await self._domain_node(name)

    async def rename_business_domain(
        self, raw_name: str, raw_new_name: str, if_match: str | None
    ) -> KnowledgeTreeNode:
        name = self._validate_domain_name(raw_name)
        new_name = self._validate_domain_name(raw_new_name)
        source = await self._domain_node(name)
        self._require_version_value(if_match, source.version)
        if name == new_name:
            return source
        if await self._domain_exists(new_name):
            raise KnowledgeAdminError(ErrorCode.WIKI_NODE_EXISTS, "同名业务域已存在", 409)
        await self._documents.move_prefix(f"业务/{name}/", f"业务/{new_name}/")
        await self._session.flush()
        return await self._domain_node(new_name)

    async def delete_business_domain(
        self, raw_name: str, if_match: str | None, *, recursive: bool
    ) -> None:
        name = self._validate_domain_name(raw_name)
        source = await self._domain_node(name)
        self._require_version_value(if_match, source.version)
        prefix = f"业务/{name}/"
        documents = await self._documents.list_paths(prefix)
        if documents and not recursive:
            raise KnowledgeAdminError(
                ErrorCode.WIKI_DIRECTORY_NOT_EMPTY,
                "业务域包含文档，确认后使用 recursive=true",
                409,
            )
        for document in documents:
            await self._documents.delete(document)
        await self._session.flush()

    async def _domain_node(self, name: str) -> KnowledgeTreeNode:
        business = self._business_root(await self._documents.list_paths("业务/"))
        for domain in business.children:
            if domain.name == name:
                return domain
        raise KnowledgeAdminError(ErrorCode.WIKI_NODE_NOT_FOUND, "业务域不存在", 404)

    async def _domain_exists(self, name: str) -> bool:
        documents = await self._documents.list_paths("业务/")
        return any(
            len(document.source_path.split("/")) >= 2
            and document.source_path.split("/")[1].casefold() == name.casefold()
            for document in documents
        )

    async def _require_maintained_document(self, path: str) -> KnowledgeDocument:
        document = await self._documents.get_by_path(path)
        if document is None:
            raise KnowledgeAdminError(ErrorCode.WIKI_NODE_NOT_FOUND, "知识文档不存在", 404)
        return document

    async def _get_memory_document(self, path: str) -> KnowledgeDocumentResponse:
        segments = path.split("/")
        if len(segments) != 4 or segments[:2] != ["memory", "merchants"]:
            raise KnowledgeAdminError(ErrorCode.WIKI_NODE_NOT_FOUND, "记忆文档不存在", 404)
        try:
            merchant_id = UUID(segments[2])
        except ValueError:
            raise KnowledgeAdminError(
                ErrorCode.WIKI_NODE_NOT_FOUND, "记忆文档不存在", 404
            ) from None
        category = segments[3].removesuffix(".md")
        result = await self._session.execute(
            select(MerchantMemory).where(
                MerchantMemory.merchant_id == merchant_id,
                MerchantMemory.category == category,
                MerchantMemory.status == "ACTIVE",
            )
        )
        memory = result.scalar_one_or_none()
        if memory is None:
            raise KnowledgeAdminError(ErrorCode.WIKI_NODE_NOT_FOUND, "记忆文档不存在", 404)
        return KnowledgeDocumentResponse(
            path=path,
            content=memory.content,
            read_only=True,
            version=document_version(memory.content),
        )

    @staticmethod
    def _document_response(resolved: ResolvedPath, content: str) -> KnowledgeDocumentResponse:
        return KnowledgeDocumentResponse(
            path=resolved.virtual_path,
            content=content,
            read_only=resolved.read_only,
            version=document_version(content),
        )

    @staticmethod
    def _require_version(if_match: str | None, content: str) -> None:
        from app.knowledge.versioning import parse_if_match

        supplied = parse_if_match(if_match)
        if supplied is None:
            raise KnowledgeAdminError(ErrorCode.WIKI_VERSION_REQUIRED, "缺少 If-Match 版本", 428)
        if supplied != document_version(content):
            raise KnowledgeAdminError(
                ErrorCode.WIKI_VERSION_CONFLICT, "文档已被其他维护者更新", 412
            )

    @staticmethod
    def _require_version_value(if_match: str | None, current_version: str) -> None:
        from app.knowledge.versioning import parse_if_match

        supplied = parse_if_match(if_match)
        if supplied is None:
            raise KnowledgeAdminError(ErrorCode.WIKI_VERSION_REQUIRED, "缺少 If-Match 版本", 428)
        if supplied != current_version:
            raise KnowledgeAdminError(
                ErrorCode.WIKI_VERSION_CONFLICT, "业务域已被其他维护者更新", 412
            )

    def _validate_content(self, content: str) -> None:
        if "\x00" in content:
            raise KnowledgeAdminError(
                ErrorCode.INVALID_WIKI_CONTENT, "文档内容不能包含 NUL 字节", 400
            )
        try:
            size = len(content.encode("utf-8", "strict"))
        except UnicodeEncodeError:
            raise KnowledgeAdminError(
                ErrorCode.INVALID_WIKI_ENCODING, "文档必须是有效 UTF-8", 415
            ) from None
        if size > self._max_document_bytes:
            raise KnowledgeAdminError(ErrorCode.WIKI_DOCUMENT_TOO_LARGE, "文档超过大小限制", 413)

    @staticmethod
    def _path_error(error: KnowledgePathError) -> KnowledgeAdminError:
        return KnowledgeAdminError(ErrorCode(error.code), error.message, error.status_code)

    def _resolve_readable(self, raw_path: str) -> ResolvedPath:
        try:
            return resolve_readable(raw_path)
        except KnowledgePathError as error:
            raise self._path_error(error) from None

    def _resolve_writable(self, raw_path: str) -> ResolvedPath:
        try:
            return resolve_writable_document(raw_path)
        except KnowledgePathError as error:
            raise self._path_error(error) from None

    def _validate_domain_name(self, raw_name: str) -> str:
        try:
            return validate_domain_name(raw_name)
        except KnowledgePathError as error:
            raise self._path_error(error) from None

    async def _list_active_memories(self) -> list[MerchantMemory]:
        result = await self._session.execute(
            select(MerchantMemory)
            .where(MerchantMemory.status == "ACTIVE")
            .order_by(MerchantMemory.merchant_id, MerchantMemory.category)
        )
        return list(result.scalars())

    def _index_root(self, documents: list[KnowledgeDocument]) -> KnowledgeTreeNode:
        children = [
            self._document_node(document.source_path, document.content, read_only=False)
            for document in documents
            if len(document.source_path.split("/")) == 2
        ]
        return self._directory_node("index", False, self._sorted_children(children))

    def _business_root(self, documents: list[KnowledgeDocument]) -> KnowledgeTreeNode:
        grouped: dict[str, dict[str, list[KnowledgeDocument]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for document in documents:
            segments = document.source_path.split("/")
            if len(segments) == 4 and segments[0] == "业务" and segments[2] in BUSINESS_SECTIONS:
                grouped[segments[1]][segments[2]].append(document)

        domains: list[KnowledgeTreeNode] = []
        for domain_name in sorted(grouped, key=str.casefold):
            sections = [
                self._directory_node(
                    f"业务/{domain_name}/{section}",
                    False,
                    self._sorted_children(
                        [
                            self._document_node(
                                document.source_path,
                                document.content,
                                read_only=False,
                            )
                            for document in grouped[domain_name][section]
                        ]
                    ),
                )
                for section in BUSINESS_SECTIONS
            ]
            domains.append(self._directory_node(f"业务/{domain_name}", False, sections))
        return self._directory_node("业务", False, domains)

    def _memory_root(self, memories: list[MerchantMemory]) -> KnowledgeTreeNode:
        by_merchant: dict[str, list[MerchantMemory]] = defaultdict(list)
        for memory in memories:
            by_merchant[str(memory.merchant_id)].append(memory)

        merchants = [
            self._directory_node(
                f"memory/merchants/{merchant_id}",
                True,
                self._sorted_children(
                    [
                        self._document_node(
                            f"memory/merchants/{merchant_id}/{memory.category}.md",
                            memory.content,
                            read_only=True,
                        )
                        for memory in merchant_memories
                    ]
                ),
            )
            for merchant_id, merchant_memories in by_merchant.items()
        ]
        merchants_root = self._directory_node(
            "memory/merchants", True, self._sorted_children(merchants)
        )
        return self._directory_node("memory", True, [merchants_root])

    @staticmethod
    def _document_node(path: str, content: str, *, read_only: bool) -> KnowledgeTreeNode:
        return KnowledgeTreeNode(
            name=path.rsplit("/", maxsplit=1)[-1],
            path=path,
            node_type="document",
            read_only=read_only,
            size=len(content.encode("utf-8")),
            version=document_version(content),
        )

    @staticmethod
    def _directory_node(
        path: str, read_only: bool, children: list[KnowledgeTreeNode]
    ) -> KnowledgeTreeNode:
        return KnowledgeTreeNode(
            name=path.rsplit("/", maxsplit=1)[-1],
            path=path,
            node_type="directory",
            read_only=read_only,
            size=sum(child.size for child in children),
            version=directory_version(path, [(child.path, child.version) for child in children]),
            children=children,
        )

    @staticmethod
    def _sorted_children(children: list[KnowledgeTreeNode]) -> list[KnowledgeTreeNode]:
        return sorted(
            children,
            key=lambda child: (child.node_type == "document", child.name.casefold()),
        )
