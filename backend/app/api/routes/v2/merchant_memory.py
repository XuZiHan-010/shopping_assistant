"""商家事实层与只读总结层的记忆 API。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import get_session_audit_repository, require_merchant_session
from app.api.v2_deps import get_cursor_codec
from app.core.errors import InvalidRequestError, error_responses
from app.core.session import SessionContext, principal_digest
from app.localization.locales import SupportedLocale
from app.memory.merchant_store import MerchantMemoryStore
from app.memory.owners import MerchantMemoryOwner
from app.models.memory_v2 import MerchantMemoryFact, MerchantMemorySummary
from app.repositories.audit import AuditRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.memory import (
    MemorySourceRef,
    MerchantMemoriesResponse,
    MerchantMemoryDeleteResponse,
    MerchantMemoryItem,
)
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.v2.cursor import CursorCodec, CursorScope, descending

router = APIRouter(prefix="/v2/merchant/memories", tags=["v2-merchant-memory"])
Merchant = Annotated[SessionContext, Depends(require_merchant_session)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
Locale = Annotated[SupportedLocale, Depends(get_request_locale)]
Codec = Annotated[CursorCodec, Depends(get_cursor_codec)]
PrincipalSecret = Annotated[bytes, Depends(get_principal_secret)]


def _fact_item(row: MerchantMemoryFact) -> MerchantMemoryItem:
    conversation_id, message_id = row.source_ref.split(":", 1)
    return MerchantMemoryItem(
        id=str(row.id), layer="FACT", category=row.category, content=row.content,
        source_ref=MemorySourceRef(conversation_id=conversation_id, message_id=message_id),
        updated_at=row.created_at,
    )


def _summary_item(row: MerchantMemorySummary) -> MerchantMemoryItem:
    return MerchantMemoryItem(
        id=str(row.id), layer="SUMMARY", category=row.category, content=row.content,
        source_ref=None, updated_at=row.rebuilt_at,
    )



def _owner(ctx: SessionContext) -> MerchantMemoryOwner:
    # `require_merchant_session` 已保证是商家会话；这里只把会话主体转成存储主体。
    owner = MerchantMemoryOwner.from_session(ctx)
    assert owner is not None
    return owner

@router.get(
    "", response_model=MerchantMemoriesResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def list_merchant_memories(
    ctx: Merchant, session: DbSession, codec: Codec, locale: Locale,
    principal_secret: PrincipalSecret,
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MerchantMemoriesResponse:
    store = MerchantMemoryStore(session, _owner(ctx))
    now = datetime.now(UTC)
    scope = CursorScope(
        endpoint="merchant.memories.list", role="MERCHANT",
        principal_digest=principal_digest(ctx, secret=principal_secret),
        merchant_id=str(ctx.merchant_id), resource="merchant-memory-fact", filters={},
        locale=locale.value, limit=limit,
    )
    page = codec.page(
        await store.facts(),
        key=lambda row: (
            descending(row.created_at.astimezone(UTC).isoformat()), descending(str(row.id))
        ),
        scope=scope, cursor=cursor, now=now,
    )
    summaries = (await store.active_summaries())[:20]
    return MerchantMemoriesResponse(
        facts=CursorPage[MerchantMemoryItem](
            items=[_fact_item(row) for row in page.items],
            next_cursor=page.next_cursor, has_more=page.has_more,
        ),
        summaries=[_summary_item(row) for row in summaries],
    )


@router.delete(
    "/{memory_id}", response_model=MerchantMemoryDeleteResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def delete_merchant_memory(
    memory_id: Annotated[str, Path(min_length=1, max_length=128)],
    ctx: Merchant, session: DbSession, request: Request,
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
) -> MerchantMemoryDeleteResponse:
    try:
        parsed_id = UUID(memory_id)
    except ValueError:
        parsed_id = uuid4()
    summary = await session.scalar(
        select(MerchantMemorySummary.id).where(
            MerchantMemorySummary.id == parsed_id,
            MerchantMemorySummary.merchant_id == ctx.merchant_id,
        )
    )
    if summary is not None:
        raise InvalidRequestError("总结层不能逐条删除")
    store = MerchantMemoryStore(session, _owner(ctx))

    async def fetch() -> ScopeLookupResult[MerchantMemoryFact]:
        fact = await store.owned_fact(fact_id=parsed_id)
        return ScopeLookupResult(resource=fact, target_exists=None)

    # 跨商家 / 不存在一律 403 并写 RESOURCE_SCOPE_VIOLATION 审计（R5）。
    fact = await require_owned(
        fetch, ctx=ctx, audits=audits, resource_type="merchant_memory",
        resource_id=memory_id, request_id=str(request.state.request_id),
    )
    if fact.deleted_at is not None:
        return MerchantMemoryDeleteResponse(
            deleted_id=memory_id, summary_rebuild_scheduled=False
        )
    dependent = await session.scalar(
        select(MerchantMemorySummary.id).where(
            MerchantMemorySummary.merchant_id == ctx.merchant_id,
            # 用规范化 UUID 比对：路径里的大写 UUID 与库内小写 ID 应视为同一事实（台账 M4）。
            MerchantMemorySummary.source_fact_ids.contains([str(parsed_id)]),
        )
    )
    deleted = await store.delete_fact(fact_id=parsed_id)
    await session.commit()
    return MerchantMemoryDeleteResponse(
        deleted_id=memory_id, summary_rebuild_scheduled=bool(deleted and dependent)
    )
