"""顾客记忆列表、逐条删除和偏好开关。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import get_session_audit_repository, require_bound_customer_session
from app.api.v2_deps import get_cursor_codec
from app.core.errors import error_responses
from app.core.session import SessionContext, principal_digest
from app.localization.locales import SupportedLocale
from app.memory.customer_store import RETENTION, CustomerMemoryStore
from app.memory.owners import CustomerMemoryOwner
from app.models.memory_v2 import CustomerMemory
from app.repositories.audit import AuditRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.memory import (
    CustomerMemoriesResponse,
    CustomerMemoryItem,
    MemoryPreferenceRequest,
    MemoryPreferenceResponse,
)
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.v2.cursor import CursorCodec, CursorScope, descending

router = APIRouter(prefix="/v2/shop", tags=["v2-shop-memory"])
BoundCustomer = Annotated[SessionContext, Depends(require_bound_customer_session)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
Locale = Annotated[SupportedLocale, Depends(get_request_locale)]
Codec = Annotated[CursorCodec, Depends(get_cursor_codec)]
PrincipalSecret = Annotated[bytes, Depends(get_principal_secret)]


def _item(row: CustomerMemory, shop_slug: str) -> CustomerMemoryItem:
    return CustomerMemoryItem(
        id=str(row.id), shop_slug=shop_slug, category=row.category,
        key=row.key, value=row.value, last_confirmed_at=row.last_confirmed_at,
        expires_at=row.last_confirmed_at + RETENTION,
    )



def _owner(ctx: SessionContext) -> CustomerMemoryOwner:
    # `BoundCustomer` 依赖已保证是已绑定顾客会话；这里只把会话主体转成存储主体。
    owner = CustomerMemoryOwner.from_session(ctx)
    assert owner is not None
    return owner

@router.get(
    "/memories", response_model=CustomerMemoriesResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def list_shop_memories(
    ctx: BoundCustomer, session: DbSession, codec: Codec, locale: Locale,
    principal_secret: PrincipalSecret,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CustomerMemoriesResponse:
    assert ctx.buyer_key is not None and ctx.shop_slug is not None
    store = CustomerMemoryStore(session, _owner(ctx))
    now = datetime.now(UTC)
    rows = await store.recall(at=now, limit=10_000)
    scope = CursorScope(
        endpoint="shop.memories.list", role="CUSTOMER",
        principal_digest=principal_digest(ctx, secret=principal_secret),
        merchant_id=str(ctx.merchant_id), resource="customer-memory", filters={},
        locale=locale.value, limit=limit,
    )
    page = codec.page(
        rows,
        key=lambda row: (
            descending(row.last_confirmed_at.astimezone(UTC).isoformat()),
            descending(str(row.id)),
        ),
        scope=scope, cursor=cursor, now=now,
    )
    return CustomerMemoriesResponse(
        memory_enabled=await store.memory_enabled(),
        memories=CursorPage[CustomerMemoryItem](
            items=[_item(row, ctx.shop_slug) for row in page.items],
            next_cursor=page.next_cursor, has_more=page.has_more,
        ),
    )


@router.delete(
    "/memories/{memory_id}", status_code=204, response_class=Response,
    responses=error_responses(401, 403, 422, 503),
)
async def delete_shop_memory(
    memory_id: Annotated[str, Path(min_length=1, max_length=128)],
    ctx: BoundCustomer, session: DbSession, request: Request,
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
) -> Response:
    owner = _owner(ctx)
    try:
        parsed_id = UUID(memory_id)
    except ValueError:
        parsed_id = uuid4()

    async def fetch() -> ScopeLookupResult[bool]:
        # 一次按主体过滤的删除即定生死：他人记忆与不存在的 ID 走同一条查询（时序侧信道，§12.1）。
        deleted = await CustomerMemoryStore(session, owner).delete(memory_id=parsed_id)
        return ScopeLookupResult(resource=True if deleted else None, target_exists=None)

    # 跨顾客 / 不存在一律 403 并写 RESOURCE_SCOPE_VIOLATION 审计（R5）。
    await require_owned(
        fetch, ctx=ctx, audits=audits, resource_type="customer_memory",
        resource_id=memory_id, request_id=str(request.state.request_id),
    )
    await session.commit()
    return Response(status_code=204)


@router.put(
    "/memory-preference", response_model=MemoryPreferenceResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def set_shop_memory_preference(
    payload: MemoryPreferenceRequest, ctx: BoundCustomer, session: DbSession,
) -> MemoryPreferenceResponse:
    purged = await CustomerMemoryStore(session, _owner(ctx)).set_preference(
        enabled=payload.enabled
    )
    await session.commit()
    return MemoryPreferenceResponse(memory_enabled=payload.enabled, purged_count=purged)
