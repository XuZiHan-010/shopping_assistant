"""管理员知识库维护端点。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    build_guarded_llm,
    get_app_settings,
    get_database,
    get_db_session,
    require_admin_or_viewer_token,
    require_admin_token,
)
from app.core.config import Settings
from app.core.errors import ResourceNotFoundError, error_responses
from app.db.session import Database
from app.llm.client import LlmBudget
from app.localization.locales import SupportedLocale
from app.repositories.audit import AuditRepository
from app.repositories.localization import LocalizationRepository
from app.repositories.merchant import MerchantRepository
from app.schemas.knowledge import (
    BusinessDomainRenameRequest,
    BusinessDomainRequest,
    KnowledgeDocumentRequest,
    KnowledgeDocumentResponse,
    KnowledgeDocumentUpdateRequest,
    KnowledgeTreeNode,
    KnowledgeTreeResponse,
    MemoryCompressRequest,
    MemoryCompressResponse,
)
from app.services.knowledge_admin_service import KnowledgeAdminService, MemoryLocalizerFactory
from app.services.localization_service import LocalizationService
from app.services.memory_admin_service import MemoryAdminService

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])

#: 只读记忆节点机器翻译的独立小额预算：管理后台一次只翻译一份记忆正文,
#: 不是聊天链路的批量结构化载荷，不需要复用 `Settings.localization_max_*`
#: 那套按请求批量预算。
_MEMORY_TRANSLATION_MAX_TOKENS = 4_000


@router.get("/tree", response_model=KnowledgeTreeResponse, responses=error_responses(401, 403, 422))
async def get_knowledge_tree(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin_or_viewer_token)],
    content_locale: Annotated[SupportedLocale | None, Query()] = None,
) -> KnowledgeTreeResponse:
    return await KnowledgeAdminService(session).tree(content_locale=content_locale)


def _set_etag(response: Response, version: str) -> None:
    response.headers["ETag"] = f'"{version}"'


def _build_memory_localizer_factory(
    session: AsyncSession,
    settings: Settings,
    database: Database,
    request: Request,
) -> MemoryLocalizerFactory:
    """返回一个只在真正需要翻译某份记忆时才被调用的构造函数。

    `merchant_id` 在这里还不知道——`GET /api/admin/knowledge/documents/{path}`
    的路径本身要先解析、这份记忆要先从数据库读出来才能确定它属于哪个商家。
    因此这里只装配"给我 merchant_id，我就还你一个按这个商家计费的
    guarded LLM 客户端"这件事本身，真正的 `build_guarded_llm()` 调用（也就是
    `llm_usage` 记账真正发生的地方）推迟到 `KnowledgeAdminService.
    _get_memory_document()` 内部、拿到 `memory.merchant_id` 之后才执行——这样
    机器翻译产生的费用才会记在触发它的商家名下，而不是像
    `build_global_guarded_llm()` 那样落进 `merchant_id=NULL` 的全局桶
    （复审 Finding 1）。请求语言与记忆 `source_locale` 一致时这个函数
    完全不会被调用，本身不产生任何 LLM 调用或额外查询。
    """

    def build(merchant_id: UUID) -> tuple[LocalizationService, LlmBudget]:
        guard = build_guarded_llm(
            settings,
            database,
            request_id=str(request.state.request_id),
            merchant_id=merchant_id,
            purpose="LOCALIZATION",
        )
        localizer = LocalizationService(
            LocalizationRepository(session),
            guard,
            max_batch_items=settings.localization_max_batch_items,
            max_batch_chars=settings.localization_max_batch_chars,
            model=settings.llm_model,
        )
        budget = LlmBudget(max_calls=1, max_tokens=_MEMORY_TRANSLATION_MAX_TOKENS)
        return localizer, budget

    return build


def _service(
    session: AsyncSession,
    settings: Settings,
    *,
    request: Request | None = None,
    database: Database | None = None,
) -> KnowledgeAdminService:
    """知识文档的人工译文增删查（`localization`）永远装配——零 LLM。
    只读记忆节点的机器翻译兜底（`memory_localizer_factory`）需要
    `request`/`database` 才能在需要时构造按商家计费的模型客户端；写端点
    （创建/更新/删除文档、业务域维护）都不会触达这条路径，调用时省略这两个
    参数即可。
    """

    memory_localizer_factory: MemoryLocalizerFactory | None = None
    if request is not None and database is not None:
        memory_localizer_factory = _build_memory_localizer_factory(
            session, settings, database, request
        )
    return KnowledgeAdminService(
        session,
        max_document_bytes=settings.knowledge_max_document_bytes,
        localization=LocalizationRepository(session),
        memory_localizer_factory=memory_localizer_factory,
    )


@router.get(
    "/documents/{document_path:path}",
    response_model=KnowledgeDocumentResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def get_document(
    document_path: str,
    response: Response,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_or_viewer_token)],
    content_locale: Annotated[SupportedLocale | None, Query()] = None,
) -> KnowledgeDocumentResponse:
    """`content_locale` 缺省时行为与本字段引入前完全一致：原样返回源正文，
    不涉及任何人工译文查找或记忆机器翻译（Task 8 向后兼容）。"""

    document = await _service(session, settings, request=request, database=database).get_document(
        document_path, content_locale=content_locale
    )
    _set_etag(response, document.version)
    return document


@router.post(
    "/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 409, 413, 415, 422),
)
async def create_document(
    payload: KnowledgeDocumentRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> KnowledgeDocumentResponse:
    document = await _service(session, settings).create_document(payload.path, payload.content)
    await session.commit()
    _set_etag(response, document.version)
    return document


@router.put(
    "/documents/{document_path:path}",
    response_model=KnowledgeDocumentResponse,
    responses=error_responses(400, 401, 403, 404, 412, 413, 415, 422, 428),
)
async def update_document(
    document_path: str,
    payload: KnowledgeDocumentUpdateRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
    if_match: Annotated[str | None, Header()] = None,
) -> KnowledgeDocumentResponse:
    document = await _service(session, settings).update_document(
        document_path,
        payload.content,
        if_match,
        is_source_version=payload.is_source_version,
        content_locale=payload.content_locale,
    )
    await session.commit()
    _set_etag(response, document.version)
    return document


@router.delete(
    "/documents/{document_path:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 403, 404, 412, 422, 428),
)
async def delete_document(
    document_path: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
    if_match: Annotated[str | None, Header()] = None,
) -> Response:
    await _service(session, settings).delete_document(document_path, if_match)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/business-domains",
    response_model=KnowledgeTreeNode,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 409, 422),
)
async def create_business_domain(
    payload: BusinessDomainRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> KnowledgeTreeNode:
    domain = await _service(session, settings).create_business_domain(payload.name)
    await session.commit()
    return domain


@router.put(
    "/business-domains",
    response_model=KnowledgeTreeNode,
    responses=error_responses(400, 401, 403, 404, 409, 412, 422, 428),
)
async def rename_business_domain(
    name: str,
    payload: BusinessDomainRenameRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
    if_match: Annotated[str | None, Header()] = None,
) -> KnowledgeTreeNode:
    domain = await _service(session, settings).rename_business_domain(
        name, payload.new_name, if_match
    )
    await session.commit()
    return domain


@router.delete(
    "/business-domains",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 403, 404, 409, 412, 422, 428),
)
async def delete_business_domain(
    name: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
    recursive: bool = False,
    if_match: Annotated[str | None, Header()] = None,
) -> Response:
    await _service(session, settings).delete_business_domain(name, if_match, recursive=recursive)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/memories/compress",
    response_model=MemoryCompressResponse,
    responses=error_responses(401, 403, 404, 422),
)
async def compress_memory(
    payload: MemoryCompressRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> MemoryCompressResponse:
    """以管理员身份手动重压指定商家的分类记忆。"""

    display_name = await MerchantRepository(session).get_display_name(payload.merchant_id)
    if display_name is None:
        raise ResourceNotFoundError("商家")

    service = MemoryAdminService(
        session,
        llm=build_guarded_llm(
            settings,
            database,
            request_id=str(request.state.request_id),
            merchant_id=payload.merchant_id,
        ),
        audit=AuditRepository(database),
    )
    return await service.compress(
        merchant_id=payload.merchant_id,
        display_name=display_name,
        category=payload.category.value,
        manual_markdown=payload.manual_markdown,
        request_id=str(request.state.request_id),
    )
