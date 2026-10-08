"""顾客订单（PRD C4–C5，契约 §8.10.3）：下单、列表、详情、履约事件、模拟支付与取消。

全部要求**已绑定演示顾客**的会话；访客 403 CUSTOMER_BINDING_REQUIRED。
`buyer_key` 与 `merchant_id` 只从会话解析；金额、库存、状态迁移全部在应用服务的单一事务里完成，
路由只做鉴权、Schema 与提交。下单、支付、取消按 §8.7.3 携带 `client_request_id`。
不存在、非本人、别家店、历史订单一律 403 RESOURCE_FORBIDDEN（`require_owned`，R5）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import get_session_audit_repository, require_bound_customer_session
from app.api.v2_deps import get_cursor_codec
from app.core.errors import InvalidCursorError, error_responses
from app.core.session import SessionContext, principal_digest
from app.localization.locales import SupportedLocale
from app.repositories.audit import AuditRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.trade import (
    FulfillmentEvent,
    FulfillmentEventPage,
    OrderCancelRequest,
    OrderCreateRequest,
    OrderDetailResponse,
    OrderPayRequest,
    OrderSummary,
)
from app.services.v2.checkout import place_order
from app.services.v2.cursor import CursorCodec, CursorScope, descending
from app.services.v2.orders import (
    fulfillment_events,
    last_event_times,
    list_owned_orders,
    order_items,
    order_leads,
    require_owned_order,
    sort_timestamp,
    to_order_detail,
    to_order_summary,
)
from app.services.v2.payment import cancel_order, expire_if_due, pay_order

router = APIRouter(prefix="/v2/shop/orders", tags=["v2-shop-orders"])

OrderIdPath = Annotated[str, Path(min_length=1, max_length=128)]
CursorQuery = Annotated[str | None, Query(min_length=1, max_length=2048)]
LimitQuery = Annotated[int, Query(ge=1, le=100)]
BoundCustomer = Annotated[SessionContext, Depends(require_bound_customer_session)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
Audits = Annotated[AuditRepository, Depends(get_session_audit_repository)]
PrincipalSecret = Annotated[bytes, Depends(get_principal_secret)]


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _scope(
    ctx: SessionContext,
    secret: bytes,
    *,
    endpoint: str,
    resource: str,
    locale: SupportedLocale,
    limit: int,
    filters: dict[str, Any] | None = None,
) -> CursorScope:
    """游标绑定端点 + 会话主体 + 店铺 + 资源 + 语言 + 每页大小（§8.10.3）；事件另绑 order_id。"""

    return CursorScope(
        endpoint=endpoint,
        role=ctx.role.value,
        principal_digest=principal_digest(ctx, secret=secret),
        merchant_id=str(ctx.merchant_id),
        resource=resource,
        filters=filters or {},
        locale=locale.value,
        limit=limit,
    )


async def _page[T](
    codec: CursorCodec,
    items: Sequence[T],
    *,
    key: Callable[[T], tuple[str, ...]],
    scope: CursorScope,
    cursor: str | None,
    ctx: SessionContext,
    audits: AuditRepository,
    request_id: str,
) -> CursorPage[T]:
    """跨主体、跨资源或被篡改的游标：422 INVALID_CURSOR，不返回数据，并写审计（§8.7.4）。"""

    try:
        return codec.page(items, key=key, scope=scope, cursor=cursor, now=datetime.now(UTC))
    except InvalidCursorError:
        await audits.record_event(
            merchant_id=ctx.merchant_id,
            event_type="INVALID_CURSOR",
            resource_type=scope.resource.lower(),
            request_id=request_id,
            metadata={"endpoint": scope.endpoint},
        )
        raise


@router.post(
    "",
    response_model=OrderDetailResponse,
    status_code=201,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def create_order(
    payload: OrderCreateRequest,
    ctx: BoundCustomer,
    session: DbSession,
    principal_secret: PrincipalSecret,
) -> JSONResponse:
    """订单行来自当前购物车；同一事务创建订单、占库、写事件，任一失败整体回滚。

    幂等重放返回第一次的响应体，状态码同样是 201。
    """

    body = await place_order(
        session,
        ctx=ctx,
        coupon_id=payload.coupon_id,
        client_request_id=payload.client_request_id,
        principal_secret=principal_secret,
        now=datetime.now(UTC),
    )
    await session.commit()
    return JSONResponse(status_code=201, content=body)


@router.get(
    "",
    response_model=CursorPage[OrderSummary],
    responses=error_responses(401, 403, 422, 503),
)
async def list_orders(
    request: Request,
    ctx: BoundCustomer,
    session: DbSession,
    audits: Audits,
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    principal_secret: PrincipalSecret,
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: CursorQuery = None,
    limit: LimitQuery = 20,
) -> CursorPage[OrderSummary]:
    """仅本人本店订单（merchant_id + buyer_key 双重过滤）；`created_at DESC, id DESC`。"""

    rows = await list_owned_orders(session, ctx)
    page = await _page(
        codec,
        rows,
        key=lambda row: (descending(sort_timestamp(row[0].placed_at)), descending(str(row[0].id))),
        scope=_scope(
            ctx,
            principal_secret,
            endpoint="shop.orders.list",
            resource="ORDER",
            locale=locale,
            limit=limit,
        ),
        cursor=cursor,
        ctx=ctx,
        audits=audits,
        request_id=_request_id(request),
    )
    # 只对分页后的当前页批量取首件商品与最近事件时间，避免全量查询（Task 3 步骤 5）。
    page_orders = [order for order, _ in page.items]
    leads = await order_leads(session, page_orders)
    last_events = await last_event_times(session, page_orders)
    return CursorPage[OrderSummary](
        items=[
            to_order_summary(
                order,
                item_count=count,
                lead_item=leads[order.id],
                last_event_at=last_events[order.id],
            )
            for order, count in page.items
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/{order_id}",
    response_model=OrderDetailResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def get_order(
    order_id: OrderIdPath,
    request: Request,
    ctx: BoundCustomer,
    session: DbSession,
    audits: Audits,
) -> OrderDetailResponse:
    """详情不内嵌事件数组，履约事件只由 `/events` 游标分页提供（§8.10.2 不变量 1）。"""

    order = await require_owned_order(
        session, ctx=ctx, order_id=order_id, audits=audits, request_id=_request_id(request)
    )
    leads = await order_leads(session, [order])
    last_events = await last_event_times(session, [order])
    return to_order_detail(
        order,
        await order_items(session, order.id),
        lead_image_url=leads[order.id].image_url,
        last_event_at=last_events[order.id],
    )


@router.get(
    "/{order_id}/events",
    response_model=FulfillmentEventPage,
    responses=error_responses(401, 403, 422, 503),
)
async def list_order_events(
    order_id: OrderIdPath,
    request: Request,
    ctx: BoundCustomer,
    session: DbSession,
    audits: Audits,
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    principal_secret: PrincipalSecret,
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: CursorQuery = None,
    limit: LimitQuery = 20,
) -> FulfillmentEventPage:
    """履约事件 `occurred_at ASC, id ASC`；游标另绑定 order_id。"""

    order = await require_owned_order(
        session, ctx=ctx, order_id=order_id, audits=audits, request_id=_request_id(request)
    )
    events = await fulfillment_events(session, order)
    page: CursorPage[FulfillmentEvent] = await _page(
        codec,
        events,
        key=lambda event: (sort_timestamp(event.occurred_at), event.id),
        scope=_scope(
            ctx,
            principal_secret,
            endpoint="shop.orders.events",
            resource="FULFILLMENT_EVENT",
            locale=locale,
            limit=limit,
            filters={"order_id": str(order.id)},
        ),
        cursor=cursor,
        ctx=ctx,
        audits=audits,
        request_id=_request_id(request),
    )
    return FulfillmentEventPage(
        items=page.items, next_cursor=page.next_cursor, has_more=page.has_more
    )


@router.post(
    "/{order_id}/pay",
    response_model=OrderDetailResponse,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def pay(
    order_id: OrderIdPath,
    payload: OrderPayRequest,
    request: Request,
    ctx: BoundCustomer,
    session: DbSession,
    audits: Audits,
    principal_secret: PrincipalSecret,
) -> JSONResponse:
    """模拟支付。已过 `pay_by` 视为已关闭：先单独提交关单与释放占用，再返回 409。"""

    now = datetime.now(UTC)
    if await expire_if_due(session, ctx=ctx, order_id=order_id, now=now):
        await session.commit()
    body = await pay_order(
        session,
        ctx=ctx,
        order_id=order_id,
        client_request_id=payload.client_request_id,
        principal_secret=principal_secret,
        audits=audits,
        request_id=_request_id(request),
        now=now,
    )
    await session.commit()
    return JSONResponse(content=body)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderDetailResponse,
    responses=error_responses(401, 403, 409, 422, 503),
)
async def cancel(
    order_id: OrderIdPath,
    payload: OrderCancelRequest,
    request: Request,
    ctx: BoundCustomer,
    session: DbSession,
    audits: Audits,
    principal_secret: PrincipalSecret,
) -> JSONResponse:
    """仅 `PENDING` 可取消，成功释放占用；已过 `pay_by` 的订单按超时关闭后返回 409。"""

    now = datetime.now(UTC)
    if await expire_if_due(session, ctx=ctx, order_id=order_id, now=now):
        await session.commit()
    body = await cancel_order(
        session,
        ctx=ctx,
        order_id=order_id,
        client_request_id=payload.client_request_id,
        principal_secret=principal_secret,
        audits=audits,
        request_id=_request_id(request),
        now=now,
    )
    await session.commit()
    return JSONResponse(content=body)
