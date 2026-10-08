"""顾客售后申请：同一路径先签发界面确认挑战，再凭一次性证据创建单据。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    build_guarded_llm,
    get_app_settings,
    get_database,
    get_db_session,
    get_principal_secret,
    get_request_locale,
)
from app.api.session_deps import get_session_audit_repository, require_bound_customer_session
from app.api.v2_deps import get_cursor_codec, get_signing_secret
from app.core.config import Settings
from app.core.errors import InvalidCursorError, error_responses
from app.core.session import SessionContext, principal_digest
from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.repositories.audit import AuditRepository
from app.schemas.v2.after_sales import (
    AfterSaleConfirmationChallenge,
    AfterSaleCreateRequest,
    AfterSaleSummary,
    AfterSaleSupplementRequest,
    CustomerAfterSaleDetailResponse,
)
from app.schemas.v2.common import CursorPage
from app.services.v2.after_sales import (
    add_supplement,
    confirm_after_sale,
    issue_challenge,
    list_sales,
    require_owned_sale,
    sale_detail,
    to_summary,
)
from app.services.v2.approval_evidence import ApprovalEvidenceService
from app.services.v2.cursor import CursorCodec, CursorScope, descending
from app.services.v2.orders import sort_timestamp

router = APIRouter(prefix="/v2/shop/after-sales", tags=["v2-shop-after-sales"])


@router.post(
    "",
    response_model=AfterSaleConfirmationChallenge,
    responses={
        201: {"model": AfterSaleSummary, "description": "界面确认后创建成功"},
        **error_responses(401, 403, 409, 422, 503),
    },
)
async def create_after_sale(
    payload: AfterSaleCreateRequest,
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_bound_customer_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
    signing_secret: Annotated[str, Depends(get_signing_secret)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
) -> JSONResponse:
    now = datetime.now(UTC)
    evidence = ApprovalEvidenceService(secret=signing_secret, purpose="customer-confirmation:v1")
    request_id = str(getattr(request.state, "request_id", "unknown"))
    if payload.confirmation_token is None:
        challenge = await issue_challenge(
            session, ctx=ctx, payload=payload, audits=audits,
            request_id=request_id, now=now, evidence=evidence, secret=principal_secret,
            summary_llm=build_guarded_llm(
                settings, database, request_id=request_id, merchant_id=ctx.merchant_id,
                role=ctx.role,
            ),
        )
        await session.commit()
        return JSONResponse(
            status_code=200, content=challenge.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )
    body = await confirm_after_sale(
        session, ctx=ctx, payload=payload, audits=audits,
        request_id=request_id, now=now, evidence=evidence, secret=principal_secret,
    )
    await session.commit()
    return JSONResponse(status_code=201, content=body)


@router.get(
    "", response_model=CursorPage[AfterSaleSummary], responses=error_responses(401, 403, 422, 503)
)
async def list_after_sales(
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_bound_customer_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CursorPage[AfterSaleSummary]:
    scope = CursorScope(
        endpoint="shop.after_sales.list", role=ctx.role.value,
        principal_digest=principal_digest(ctx, secret=secret),
        merchant_id=str(ctx.merchant_id), resource="AFTER_SALE",
        filters={}, locale=locale.value, limit=limit,
    )
    rows = await list_sales(session, ctx, customer=True)
    try:
        page = codec.page(
            rows,
            key=lambda row: (
                descending(sort_timestamp(row.created_at)), descending(str(row.id))
            ),
            scope=scope, cursor=cursor, now=datetime.now(UTC),
        )
    except InvalidCursorError:
        await audits.record_event(
            merchant_id=ctx.merchant_id, event_type="INVALID_CURSOR",
            resource_type="after_sale", request_id=str(request.state.request_id),
            metadata={"endpoint": scope.endpoint},
        )
        raise
    return CursorPage[AfterSaleSummary](
        items=[to_summary(item) for item in page.items],
        next_cursor=page.next_cursor, has_more=page.has_more,
    )


@router.get(
    "/{after_sale_id}", response_model=CustomerAfterSaleDetailResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def get_after_sale(
    after_sale_id: str,
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_bound_customer_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
) -> CustomerAfterSaleDetailResponse:
    record = await require_owned_sale(
        session, ctx=ctx, sale_id=after_sale_id, audits=audits,
        request_id=str(request.state.request_id), customer=True,
    )
    detail = await sale_detail(session, record, customer=True)
    assert isinstance(detail, CustomerAfterSaleDetailResponse)
    return detail


@router.post(
    "/{after_sale_id}/supplements", response_model=AfterSaleSummary,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def supplement_after_sale(
    after_sale_id: str,
    payload: AfterSaleSupplementRequest,
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_bound_customer_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
) -> AfterSaleSummary:
    body = await add_supplement(
        session, ctx=ctx, sale_id=after_sale_id, payload=payload,
        secret=secret, audits=audits,
        request_id=str(request.state.request_id), now=datetime.now(UTC),
    )
    await session.commit()
    return AfterSaleSummary.model_validate(body)
