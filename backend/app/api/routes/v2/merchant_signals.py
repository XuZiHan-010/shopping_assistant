"""商家顾客信号队列：聚合提醒与显式忽略。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import get_session_audit_repository, require_merchant_session
from app.api.v2_deps import get_cursor_codec, merchant_cursor_scope
from app.core.errors import InvalidCursorError, error_responses
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.memory_v2 import CustomerSignal as SignalRow
from app.repositories.audit import AuditRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.merchant_ops import CustomerSignal, SignalIgnoreRequest
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.v2.cursor import CursorCodec, descending
from app.services.v2.customer_signals import ignore_signal, list_signals, to_signal

router = APIRouter(prefix="/v2/merchant/customer-signals", tags=["v2-merchant-signals"])


@router.get(
    "", response_model=CursorPage[CustomerSignal],
    responses=error_responses(401, 403, 422, 503),
)
async def get_signals(
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    include_ignored: bool = False,
) -> CursorPage[CustomerSignal]:
    scope = merchant_cursor_scope(
        ctx, endpoint="merchant.customer_signals.list", resource="CUSTOMER_SIGNAL",
        filters={"include_ignored": include_ignored}, locale=locale,
        limit=limit, secret=secret,
    )
    rows = await list_signals(session, ctx, include_ignored=include_ignored)
    try:
        page = codec.page(
            rows, key=lambda row: (
                descending(row.signal_date.isoformat()), descending(str(row.id))
            ), scope=scope, cursor=cursor, now=datetime.now(UTC),
        )
    except InvalidCursorError:
        await audits.record_event(
            merchant_id=ctx.merchant_id, event_type="INVALID_CURSOR",
            resource_type="customer_signal", request_id=str(request.state.request_id),
            metadata={"endpoint": scope.endpoint},
        )
        raise
    return CursorPage[CustomerSignal](
        items=[to_signal(row) for row in page.items],
        next_cursor=page.next_cursor, has_more=page.has_more,
    )


@router.post(
    "/{signal_id}/ignore", response_model=CustomerSignal,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def ignore_customer_signal(
    signal_id: str,
    payload: SignalIgnoreRequest,
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
) -> CustomerSignal:
    try:
        target = UUID(signal_id)
    except ValueError:
        target = None

    async def fetch() -> ScopeLookupResult[SignalRow]:
        row = await session.scalar(select(SignalRow).where(
            SignalRow.id == target, SignalRow.merchant_id == ctx.merchant_id
        ))
        return ScopeLookupResult(resource=row, target_exists=None)

    row = await require_owned(
        fetch, ctx=ctx, audits=audits, resource_type="customer_signal",
        resource_id=signal_id, request_id=str(request.state.request_id),
    )
    result = await ignore_signal(
        session, ctx=ctx, row=row, payload=payload, secret=secret
    )
    await session.commit()
    return CustomerSignal.model_validate(result)
