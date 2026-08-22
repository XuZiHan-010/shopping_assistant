"""管理员知识库维护端点。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    build_guarded_llm,
    get_app_settings,
    get_database,
    get_db_session,
    require_admin_token,
)
from app.core.config import Settings
from app.core.errors import ResourceNotFoundError, error_responses
from app.db.session import Database
from app.repositories.audit import AuditRepository
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
from app.services.knowledge_admin_service import KnowledgeAdminService
from app.services.memory_admin_service import MemoryAdminService

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])


@router.get("/tree", response_model=KnowledgeTreeResponse, responses=error_responses(401, 403, 422))
async def get_knowledge_tree(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> KnowledgeTreeResponse:
    return await KnowledgeAdminService(session).tree()


def _set_etag(response: Response, version: str) -> None:
    response.headers["ETag"] = f'"{version}"'


def _service(session: AsyncSession, settings: Settings) -> KnowledgeAdminService:
    return KnowledgeAdminService(session, max_document_bytes=settings.knowledge_max_document_bytes)


@router.get(
    "/documents/{document_path:path}",
    response_model=KnowledgeDocumentResponse,
    responses=error_responses(400, 401, 403, 404, 422),
)
async def get_document(
    document_path: str,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> KnowledgeDocumentResponse:
    document = await _service(session, settings).get_document(document_path)
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
        document_path, payload.content, if_match
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
