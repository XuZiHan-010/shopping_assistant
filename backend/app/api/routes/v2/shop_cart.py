"""顾客购物车（PRD C3，契约 §8.10.3）：访客与已绑定顾客都可使用。

`PUT` 设置**绝对数量**、`DELETE` 删除一行，两者天然幂等，不带 `client_request_id`（§8.7.3）。
购物车不占库存；主体只从 `X-Session-Id` 解析，请求里没有任何身份字段。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session
from app.api.session_deps import get_session_audit_repository, require_customer_session
from app.core.errors import error_responses
from app.core.session import SessionContext
from app.repositories.audit import AuditRepository
from app.schemas.v2.trade import CartItemSetRequest, CartResponse
from app.services.v2.cart import CartService

router = APIRouter(prefix="/v2/shop/cart", tags=["v2-shop-cart"])

ProductIdPath = Annotated[str, Path(min_length=1, max_length=128)]


def get_cart_service(
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_customer_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
) -> CartService:
    return CartService(
        session,
        ctx=ctx,
        audits=audits,
        request_id=str(getattr(request.state, "request_id", "unknown")),
    )


@router.get("", response_model=CartResponse, responses=error_responses(401, 403, 422, 503))
async def get_cart(service: Annotated[CartService, Depends(get_cart_service)]) -> CartResponse:
    return await service.view()


@router.put(
    "/items/{product_id}",
    response_model=CartResponse,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def set_cart_item(
    product_id: ProductIdPath,
    payload: CartItemSetRequest,
    service: Annotated[CartService, Depends(get_cart_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CartResponse:
    """非本店、不可售、标识不合法统一 403 PRODUCT_NOT_IN_SCOPE；售罄 409 INSUFFICIENT_STOCK。"""

    cart = await service.set_quantity(product_id, payload.quantity)
    await session.commit()
    return cart


@router.delete(
    "/items/{product_id}",
    response_model=CartResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def remove_cart_item(
    product_id: ProductIdPath,
    service: Annotated[CartService, Depends(get_cart_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CartResponse:
    """商品不在购物车时同样 200，不探测商品是否存在。"""

    cart = await service.remove(product_id)
    await session.commit()
    return cart
