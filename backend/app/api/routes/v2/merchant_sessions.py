"""商家 Token 换会话与注销（PRD §11.2.3，契约 §8.9.2）。

N1 内唯一落地的商家侧 v2 路由；其余商家端点（指标、草稿、客服等）归 N2 及之后。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security.utils import get_authorization_scheme_param
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_rate_limit, get_db_session, get_merchant_context
from app.api.session_deps import get_session_service, require_merchant_session
from app.core.errors import error_responses
from app.core.security import MerchantContext
from app.core.session import SessionContext
from app.repositories.merchant import MerchantRepository
from app.schemas.v2.merchant_session import (
    MerchantSessionCreateRequest,
    MerchantSessionCreateResponse,
)
from app.services.session_service import SessionService

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-sessions"])


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _raw_bearer_token(request: Request) -> str:
    # 与 HTTPBearer 使用同一解析器；get_merchant_context 已验证 scheme 和 token。
    # 不再按大小写剥离前缀，也不修改已通过鉴权的凭证内容。
    _, credentials = get_authorization_scheme_param(request.headers.get("authorization"))
    return credentials


@router.post(
    "/sessions",
    response_model=MerchantSessionCreateResponse,
    status_code=201,
    responses=error_responses(401, 422, 429, 503),
)
async def create_merchant_session(
    payload: MerchantSessionCreateRequest,
    request: Request,
    response: Response,
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit)],
    service: Annotated[SessionService, Depends(get_session_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MerchantSessionCreateResponse:
    """身份只来自既有演示 Bearer Token 解析（v1 行为不变）；此后一律用会话续用身份。"""

    issuer = _raw_bearer_token(request)
    token, ctx = await service.issue_merchant(context, issuer=issuer)
    profile = await MerchantRepository(session).get_session_profile(context.merchant_id)
    await session.commit()
    _no_store(response)
    assert ctx.expires_at is not None
    assert profile is not None
    display_name, shop_slug = profile
    return MerchantSessionCreateResponse(
        session_id=token,
        role=ctx.role,
        expires_at=ctx.expires_at,
        merchant_display_name=display_name,
        # 只从已验证会话对应的商家行取（R5）；请求体为空对象，传入任何字段都是 422。
        shop_slug=shop_slug,
    )


@router.delete(
    "/sessions/current",
    status_code=204,
    responses=error_responses(401, 403, 422, 503),
)
async def revoke_merchant_session(
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    service: Annotated[SessionService, Depends(get_session_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    await service.revoke(ctx)
    await session.commit()
