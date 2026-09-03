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
from app.llm.client import LlmBudget
from app.localization.catalog import localize_catalog_value
from app.localization.locales import SourceLanguage, SupportedLocale, hash_source_text
from app.localization.payloads import LocalizationServiceLike
from app.models.knowledge import KnowledgeDocument, MerchantMemory
from app.repositories.knowledge_admin import KnowledgeAdminRepository, classify_source_locale
from app.repositories.localization import (
    LocalizationRepository,
    LocalizationScope,
    ResourceLocalizationKey,
    ResourceLocalizationStatus,
)
from app.schemas.knowledge import (
    ContentLanguage,
    KnowledgeDocumentResponse,
    KnowledgeTreeNode,
    KnowledgeTreeResponse,
    TranslationStatus,
)
from app.schemas.localization import LocalizeItem

#: `KnowledgeDocument`/`MerchantMemory` 的资源类型标识，见
#: `app.repositories.localization.ResourceLocalizationKey`。知识文档的人工
#: 译文用 GLOBAL 作用域——团队知识库不按商家隔离,这与检索侧
#: `app.knowledge.retrieval` 把知识文档当全平台共享语料的既有设计一致。
_KNOWLEDGE_DOCUMENT_SCOPE = LocalizationScope(kind="GLOBAL")


def _source_language_of(value: str) -> SourceLanguage:
    """`KnowledgeDocument.source_locale` 落库的字符串恰好是 `SourceLanguage`
    每个成员的取值（`zh-CN`/`en-US`/`mixed`/`und`），直接按值构造即可。"""

    return SourceLanguage(value)


class KnowledgeAdminService:
    """由数据库文档和只读商家记忆推导维护后台目录树。

    `localization`（资源级人工译文的增删查，零 LLM）在生产环境总会传入；
    `memory_localizer`/`memory_budget` 只在读取只读记忆节点、且请求语言与
    该记忆的 `source_locale` 不同时才会被用到（机器翻译，有真实 LLM 成本），
    两者缺一即视为"本次请求无法机器翻译"，安全降级为原样返回源正文而不是
    报错——知识文档本身的人工译文读写完全不依赖这两个参数。
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        max_document_bytes: int = 262_144,
        localization: LocalizationRepository | None = None,
        memory_localizer: LocalizationServiceLike | None = None,
        memory_budget: LlmBudget | None = None,
    ) -> None:
        self._session = session
        self._documents = KnowledgeAdminRepository(session)
        self._max_document_bytes = max_document_bytes
        self._localization = localization or LocalizationRepository(session)
        self._memory_localizer = memory_localizer
        self._memory_budget = memory_budget

    async def tree(
        self, *, content_locale: SupportedLocale | None = None
    ) -> KnowledgeTreeResponse:
        """`content_locale` 只本地化节点的 `name`（导航标签），`path`
        （API 用来定位文档/记忆的真实标识符）与 `version` 永远不变——Step 4
        原文"树节点只本地化 name，API path 不变"。只有固定导航标签（"业务"
        根节点、四个 `BUSINESS_SECTIONS`）登记在 `app.localization.catalog`
        闭集词典里；用户创建的业务域名称与任意文档标题不在这张表里,词典
        未命中时原样保留——不因为翻译不到就报错或截断显示，也不为此触发
        真实模型调用（零 LLM）。"""

        index_documents = await self._documents.list_paths("index/")
        business_documents = await self._documents.list_paths("业务/")
        memory_rows = await self._list_active_memories()
        return KnowledgeTreeResponse(
            roots=[
                self._index_root(index_documents, content_locale),
                self._business_root(business_documents, content_locale),
                self._memory_root(memory_rows, content_locale),
            ]
        )

    async def get_document(
        self, raw_path: str, *, content_locale: SupportedLocale | None = None
    ) -> KnowledgeDocumentResponse:
        resolved = self._resolve_readable(raw_path)
        if not resolved.virtual_path.endswith(".md"):
            raise KnowledgeAdminError(ErrorCode.INVALID_FILE_TYPE, "只允许读取 Markdown 文档", 400)
        if resolved.read_only:
            return await self._get_memory_document(resolved.virtual_path, content_locale)
        document = await self._documents.get_by_path(resolved.virtual_path)
        if document is None:
            raise KnowledgeAdminError(ErrorCode.WIKI_NODE_NOT_FOUND, "知识文档不存在", 404)
        return await self._document_response_for_locale(resolved, document, content_locale)

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
        return self._source_document_response(resolved, document)

    async def update_document(
        self,
        raw_path: str,
        content: str,
        if_match: str | None,
        *,
        is_source_version: bool = True,
        content_locale: SupportedLocale | None = None,
    ) -> KnowledgeDocumentResponse:
        """`is_source_version=true`：更新源标题/正文并重新分类 `source_locale`；
        旧源哈希对应的机器缓存不再命中（等待 30 天自然过期，不在这里显式
        清理——见 `app.repositories.localization.LocalizationRepository.
        purge_expired_machine()`），已保存的人工译文因 `source_hash`/
        `source_version` 不再匹配而自动变为 STALE（不删除，仍可作为过期参考）。

        `is_source_version=false`：源标题/正文原样不动，只按
        `ResourceLocalizationKey(resource_type="KNOWLEDGE_DOCUMENT",
        resource_id=document.id, field_name="content")` 保存一份人工译文，
        `source_version`/`source_hash` 锁定在**当前**源版本上。

        两条路径的乐观锁都仍然只看源正文（`path` 与版本并发控制使用事实源
        记录，Step 4 原文）——编辑英文人工版本不会、也不应该绕过并发保护。
        """

        resolved = self._resolve_writable(raw_path)
        document = await self._require_maintained_document(resolved.virtual_path)
        self._require_version(if_match, document.content)
        self._validate_content(content)

        if is_source_version:
            new_source_locale = classify_source_locale(document.title, content)
            updated = await self._documents.update_content_if_current(
                document.id,
                document.content,
                content,
                source_locale=new_source_locale,
            )
            if updated is None:
                raise KnowledgeAdminError(
                    ErrorCode.WIKI_VERSION_CONFLICT, "文档已被其他维护者更新", 412
                )
            await self._session.flush()
            return self._source_document_response(resolved, updated)

        assert content_locale is not None  # 由 Pydantic 校验器保证
        await self._localization.upsert_human(
            scope=_KNOWLEDGE_DOCUMENT_SCOPE,
            key=ResourceLocalizationKey(
                resource_type="KNOWLEDGE_DOCUMENT",
                resource_id=document.id,
                field_name="content",
            ),
            target_locale=content_locale,
            source_hash=hash_source_text(document.content),
            source_version=document.version,
            source_language=_source_language_of(document.source_locale),
            translated_text=content,
        )
        await self._session.flush()
        return KnowledgeDocumentResponse(
            path=resolved.virtual_path,
            content=content,
            read_only=resolved.read_only,
            version=document_version(document.content),
            content_locale=content_locale.value,
            translation_status="CURRENT",
        )

    async def delete_document(self, raw_path: str, if_match: str | None) -> None:
        resolved = self._resolve_writable(raw_path)
        document = await self._require_maintained_document(resolved.virtual_path)
        self._require_version(if_match, document.content)
        # 先取快照再删除：`session.delete()` 之后这个实例的属性不再可靠可读。
        document_id = document.id
        source_hashes = [hash_source_text(document.title), hash_source_text(document.content)]
        await self._documents.delete(document)
        await self._localization.delete_resource_localizations(
            resource_type="KNOWLEDGE_DOCUMENT", resource_id=document_id
        )
        await self._localization.delete_machine_by_hashes(
            scope=_KNOWLEDGE_DOCUMENT_SCOPE,
            source_hashes=source_hashes,
        )
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
        business = self._business_root(await self._documents.list_paths("业务/"), None)
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

    async def _get_memory_document(
        self, path: str, content_locale: SupportedLocale | None
    ) -> KnowledgeDocumentResponse:
        """商家记忆没有人工编辑入口（Step 4）：命中且请求语言与
        `memory.source_locale` 一致时零翻译调用原样返回；不一致时按
        MERCHANT 作用域调用一次机器翻译（若本服务未装配
        `memory_localizer`/`memory_budget`，或翻译未能在预算内完成，安全
        降级为原样返回源正文并标记 `MISSING`，绝不报错、也绝不把源语言
        原文冒充成目标语言译文）。"""

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

        version = document_version(memory.content)
        source_locale: ContentLanguage = memory.source_locale  # type: ignore[assignment]
        if content_locale is None or str(content_locale) == memory.source_locale:
            return KnowledgeDocumentResponse(
                path=path,
                content=memory.content,
                read_only=True,
                version=version,
                content_locale=source_locale,
                translation_status="SOURCE",
            )

        if self._memory_localizer is not None and self._memory_budget is not None:
            resolved_texts = await self._memory_localizer.localize_many(
                scope=LocalizationScope(kind="MERCHANT", merchant_id=memory.merchant_id),
                items=[LocalizeItem(key="content", text=memory.content)],
                target_locale=content_locale,
                budget=self._memory_budget,
            )
            translated = resolved_texts.get("content")
            if translated is not None:
                return KnowledgeDocumentResponse(
                    path=path,
                    content=translated,
                    read_only=True,
                    version=version,
                    content_locale=content_locale.value,
                    translation_status="CURRENT",
                )

        return KnowledgeDocumentResponse(
            path=path,
            content=memory.content,
            read_only=True,
            version=version,
            content_locale=source_locale,
            translation_status="MISSING",
        )

    def _source_document_response(
        self, resolved: ResolvedPath, document: KnowledgeDocument
    ) -> KnowledgeDocumentResponse:
        return KnowledgeDocumentResponse(
            path=resolved.virtual_path,
            content=document.content,
            read_only=resolved.read_only,
            version=document_version(document.content),
            content_locale=document.source_locale,
            translation_status="SOURCE",
        )

    async def _document_response_for_locale(
        self,
        resolved: ResolvedPath,
        document: KnowledgeDocument,
        content_locale: SupportedLocale | None,
    ) -> KnowledgeDocumentResponse:
        """读取只返回匹配当前源版本的人工译文（Step 4 原文）：命中的译文
        `source_hash`/`source_version` 必须与 `document` 当前状态一致才算
        `CURRENT`；`STALE`（源已变化）或 `MISSING`（从未保存）都回退为源正文,
        绝不把过期或不存在的译文当作当前内容展示。"""

        if content_locale is None or str(content_locale) == document.source_locale:
            return self._source_document_response(resolved, document)

        lookup = await self._localization.get_current_resource_translation(
            scope=_KNOWLEDGE_DOCUMENT_SCOPE,
            key=ResourceLocalizationKey(
                resource_type="KNOWLEDGE_DOCUMENT",
                resource_id=document.id,
                field_name="content",
            ),
            target_locale=content_locale,
            current_source_hash=hash_source_text(document.content),
            current_source_version=document.version,
        )
        version = document_version(document.content)
        if lookup.status is ResourceLocalizationStatus.CURRENT:
            assert lookup.record is not None
            return KnowledgeDocumentResponse(
                path=resolved.virtual_path,
                content=lookup.record.translated_text,
                read_only=resolved.read_only,
                version=version,
                content_locale=content_locale.value,
                translation_status="CURRENT",
            )
        fallback_status: TranslationStatus = (
            "STALE" if lookup.status is ResourceLocalizationStatus.STALE else "MISSING"
        )
        return KnowledgeDocumentResponse(
            path=resolved.virtual_path,
            content=document.content,
            read_only=resolved.read_only,
            version=version,
            content_locale=document.source_locale,
            translation_status=fallback_status,
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

    def _index_root(
        self, documents: list[KnowledgeDocument], content_locale: SupportedLocale | None
    ) -> KnowledgeTreeNode:
        children = [
            self._document_node(
                document.source_path,
                document.content,
                read_only=False,
                content_locale=content_locale,
            )
            for document in documents
            if len(document.source_path.split("/")) == 2
        ]
        return self._directory_node(
            "index", False, self._sorted_children(children), content_locale
        )

    def _business_root(
        self, documents: list[KnowledgeDocument], content_locale: SupportedLocale | None
    ) -> KnowledgeTreeNode:
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
                                content_locale=content_locale,
                            )
                            for document in grouped[domain_name][section]
                        ]
                    ),
                    content_locale,
                )
                for section in BUSINESS_SECTIONS
            ]
            domains.append(
                self._directory_node(f"业务/{domain_name}", False, sections, content_locale)
            )
        return self._directory_node("业务", False, domains, content_locale)

    def _memory_root(
        self, memories: list[MerchantMemory], content_locale: SupportedLocale | None
    ) -> KnowledgeTreeNode:
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
                            content_locale=content_locale,
                        )
                        for memory in merchant_memories
                    ]
                ),
                content_locale,
            )
            for merchant_id, merchant_memories in by_merchant.items()
        ]
        merchants_root = self._directory_node(
            "memory/merchants", True, self._sorted_children(merchants), content_locale
        )
        return self._directory_node("memory", True, [merchants_root], content_locale)

    @staticmethod
    def _localized_name(name: str, content_locale: SupportedLocale | None) -> str:
        """只本地化树节点的 `name`（导航标签）；`path`/`version` 不受影响。
        只有登记在 `app.localization.catalog` 闭集词典里的固定标签（根节点
        "业务"、四个 `BUSINESS_SECTIONS`）才会变化——用户创建的业务域名称、
        文档标题和记忆分类文件名不在词典里，原样保留，不因未命中而报错，
        也不为此触发真实模型调用。"""

        if content_locale is None:
            return name
        return localize_catalog_value(name, content_locale) or name

    @classmethod
    def _document_node(
        cls,
        path: str,
        content: str,
        *,
        read_only: bool,
        content_locale: SupportedLocale | None = None,
    ) -> KnowledgeTreeNode:
        name = path.rsplit("/", maxsplit=1)[-1]
        return KnowledgeTreeNode(
            name=cls._localized_name(name, content_locale),
            path=path,
            node_type="document",
            read_only=read_only,
            size=len(content.encode("utf-8")),
            version=document_version(content),
        )

    @classmethod
    def _directory_node(
        cls,
        path: str,
        read_only: bool,
        children: list[KnowledgeTreeNode],
        content_locale: SupportedLocale | None = None,
    ) -> KnowledgeTreeNode:
        name = path.rsplit("/", maxsplit=1)[-1]
        return KnowledgeTreeNode(
            name=cls._localized_name(name, content_locale),
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
