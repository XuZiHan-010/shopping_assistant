"""商家售后只读队列与摘要详情；顾客标识只返回店铺级别名。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import get_session_audit_repository, require_merchant_session
from app.api.v2_deps import get_cursor_codec, merchant_cursor_scope
from app.core.errors import InvalidCursorError, error_responses
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.repositories.audit import AuditRepository
from app.schemas.v2.after_sales import (
    AfterSaleState,
    MerchantAfterSaleDetailResponse,
    MerchantAfterSaleSummary,
)
from app.schemas.v2.common import CursorPage
from app.services.v2.after_sales import (
    list_sales,
    merchant_summary,
    require_owned_sale,
    sale_detail,
)
from app.services.v2.cursor import CursorCodec, descending
from app.services.v2.orders import sort_timestamp

router = APIRouter(prefix="/v2/merchant/after-sales", tags=["v2-merchant-after-sales"])


@router.get(
    "", response_model=CursorPage[MerchantAfterSaleSummary],
    responses=error_responses(401, 403, 422, 503),
)
async def list_after_sales(
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    state: AfterSaleState | None = None,
) -> CursorPage[MerchantAfterSaleSummary]:
    scope = merchant_cursor_scope(
        ctx, endpoint="merchant.after_sales.list", resource="AFTER_SALE",
        filters={"state": state.value if state else None},
        locale=locale, limit=limit, secret=secret,
    )
    rows = await list_sales(session, ctx, customer=False, state=state.value if state else None)
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
    return CursorPage[MerchantAfterSaleSummary](
        items=[merchant_summary(item, alias_secret=secret, locale=locale) for item in page.items],
        next_cursor=page.next_cursor, has_more=page.has_more,
    )


@router.get(
    "/{after_sale_id}", response_model=MerchantAfterSaleDetailResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def get_after_sale(
    after_sale_id: str,
    request: Request,
    response: Response,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> MerchantAfterSaleDetailResponse:
    record = await require_owned_sale(
        session, ctx=ctx, sale_id=after_sale_id, audits=audits,
        request_id=str(request.state.request_id), customer=False,
    )
    await audits.record_event(
        merchant_id=ctx.merchant_id, event_type="AFTER_SALE_SUMMARY_VIEWED",
        resource_type="after_sale", resource_id=str(record.id),
        request_id=str(request.state.request_id),
        metadata={"session_record_id": str(ctx.session_record_id)},
    )
    detail = await sale_detail(session, record, customer=False, alias_secret=secret, locale=locale)
    response.headers["Cache-Control"] = "no-store"
    assert isinstance(detail, MerchantAfterSaleDetailResponse)
    return detail
