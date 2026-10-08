"""顾客会话签发、演示顾客绑定与注销（PRD §11.2.2，契约 §8.8.2）。

N1 内唯一落地的顾客侧 v2 路由；其余顾客端点（商品、购物车、订单等）归 N2 及之后。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import enforce_keyed_rate_limit, get_app_settings, get_db_session
from app.api.session_deps import get_session_service, require_customer_session
from app.core.config import Settings
from app.core.errors import ResourceNotFoundError, error_responses
from app.core.session import SessionContext
from app.schemas.v2.shop_session import (
    DemoCustomerBindRequest,
    DemoCustomerBindResponse,
    ShopSessionCreateRequest,
    ShopSessionCreateResponse,
)
from app.services.session_service import SessionService

router = APIRouter(prefix="/v2/shop", tags=["v2-shop-sessions"])


def _no_store(response: Response) -> None:
    # 会话签发/绑定响应绝不允许被浏览器或中间代理缓存复用（Task 4 规则）。
    response.headers["Cache-Control"] = "no-store"


@router.post(
    "/sessions",
    response_model=ShopSessionCreateResponse,
    status_code=201,
    responses=error_responses(403, 422, 429, 503),
)
async def create_shop_session(
    payload: ShopSessionCreateRequest,
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
    service: Annotated[SessionService, Depends(get_session_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ShopSessionCreateResponse:
    """公开端点：未知或未激活的 `shop_slug` 统一 403 RESOURCE_FORBIDDEN，不泄露店铺是否存在。"""

    enforce_keyed_rate_limit(request, settings, key=payload.shop_slug)
    token, ctx = await service.create_guest(payload.shop_slug)
    await session.commit()
    _no_store(response)
    assert ctx.expires_at is not None
    return ShopSessionCreateResponse(session_id=token, role=ctx.role, expires_at=ctx.expires_at)


@router.post(
    "/sessions/demo-customer",
    response_model=DemoCustomerBindResponse,
    responses=error_responses(401, 403, 404, 409, 422, 503),
)
async def bind_demo_customer(
    payload: DemoCustomerBindRequest,
    response: Response,
    ctx: Annotated[SessionContext, Depends(require_customer_session)],
    service: Annotated[SessionService, Depends(get_session_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> DemoCustomerBindResponse:
    """请求体是空对象：演示顾客身份完全由服务端从当前会话的店铺解析（D7②）。

    演示模式全局关闭时统一 404，不依赖 `demo_customer_identities` 是否恰好
    配置了当前店铺——两者都表示"这里不能绑演示顾客"，但分开判断更清楚：
    这条命中的是部署开关，服务层那条命中的是店铺未配置。
    """

    if not settings.demo_deployment_mode:
        raise ResourceNotFoundError("demo customer identity")
    bound, cart_adjusted = await service.bind_demo_customer(ctx)
    await session.commit()
    _no_store(response)
    assert bound.expires_at is not None
    return DemoCustomerBindResponse(
        role=bound.role,
        is_bound=True,
        expires_at=bound.expires_at,
        cart_adjusted=cart_adjusted,
    )


@router.delete(
    "/sessions/current",
    status_code=204,
    responses=error_responses(401, 403, 422, 503),
)
async def revoke_shop_session(
    ctx: Annotated[SessionContext, Depends(require_customer_session)],
    service: Annotated[SessionService, Depends(get_session_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    await service.revoke(ctx)
    await session.commit()
