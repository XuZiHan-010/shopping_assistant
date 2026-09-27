"""v2 会话鉴权依赖：与 v1 `MerchantContext` / Bearer 并存的另一套身份。

单独建这个文件而不塞进 `dependencies.py`：后者已经承载全部 v1 依赖，v2 会话是
并存的另一套鉴权，混在一起会让"这个路由用哪套身份"难以一眼看清。

管理员不进本文件的会话体系（D8⑥⑦）：`/api/admin/*` 继续只认 `X-Admin-Token`，
本模块不给管理端点加会话依赖，也不让 `X-Session-Id` 在管理端点上产生任何效果。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_database, get_db_session
from app.core.config import Settings
from app.core.errors import (
    CustomerBindingRequiredError,
    SessionInvalidError,
    SessionRequiredError,
    SessionRoleMismatchError,
)
from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.repositories.audit import AuditRepository
from app.repositories.merchant import MerchantRepository
from app.repositories.session import SessionRepository
from app.services.session_service import CartMergePort, SessionService
from app.services.v2.cart import DatabaseCartMerge


def get_session_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> SessionRepository:
    return SessionRepository(session, default_ttl_seconds=settings.session_ttl_seconds)


def get_session_audit_repository(
    database: Annotated[Database, Depends(get_database)],
) -> AuditRepository:
    return AuditRepository(database)


async def _resolve_session_context(
    session_id: str | None,
    repo: SessionRepository,
) -> SessionContext:
    if not session_id:
        raise SessionRequiredError
    context = await repo.resolve(session_id)
    if context is None:
        raise SessionInvalidError
    return context


async def _record_role_mismatch(
    request: Request,
    audits: AuditRepository,
    context: SessionContext,
) -> None:
    await audits.record_event(
        merchant_id=context.merchant_id,
        event_type="SESSION_ROLE_MISMATCH",
        resource_type="session",
        resource_id=str(context.session_record_id),
        request_id=str(request.state.request_id),
        metadata={"actual_role": context.role.value},
    )


async def require_customer_session(
    request: Request,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    session_id: Annotated[str | None, Header(alias="X-Session-Id")] = None,
) -> SessionContext:
    """顾客会话守卫。角色不符一律 403 + 审计，不降级为 401。"""

    context = await _resolve_session_context(session_id, repo)
    if context.role is not SessionRole.CUSTOMER:
        await _record_role_mismatch(request, audits, context)
        raise SessionRoleMismatchError
    return context


async def require_merchant_session(
    request: Request,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    session_id: Annotated[str | None, Header(alias="X-Session-Id")] = None,
) -> SessionContext:
    """商家会话守卫。角色不符一律 403 + 审计，不降级为 401。"""

    context = await _resolve_session_context(session_id, repo)
    if context.role is not SessionRole.MERCHANT:
        await _record_role_mismatch(request, audits, context)
        raise SessionRoleMismatchError
    return context


async def require_bound_customer_session(
    context: Annotated[SessionContext, Depends(require_customer_session)],
) -> SessionContext:
    """在顾客会话基础上要求已绑定服务端顾客身份。

    访客与已绑定顾客的 `role` 都是 `CUSTOMER`，未绑定不复用
    `SESSION_ROLE_MISMATCH`——那个码专指"这个身份不该碰这里"，
    未绑定是"这个身份还没完成前置步骤"，两者审计含义不同，此处不写审计。
    """

    if not context.is_bound:
        raise CustomerBindingRequiredError
    return context


def get_cart_merge_port() -> CartMergePort:
    """生产装配：真实的访客购物车合并（交易计划 Task 2，PRD C3）。

    N1 的 `EmptyCartMerge` 只剩测试替身用途，不得再回到这里。
    """

    return DatabaseCartMerge()


def get_session_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    cart_merge: Annotated[CartMergePort, Depends(get_cart_merge_port)],
) -> SessionService:
    return SessionService(
        session,
        merchants=MerchantRepository(session),
        sessions=SessionRepository(session, default_ttl_seconds=settings.session_ttl_seconds),
        cart_merge=cart_merge,
        demo_customer_identities=settings.demo_customer_identities,
    )
