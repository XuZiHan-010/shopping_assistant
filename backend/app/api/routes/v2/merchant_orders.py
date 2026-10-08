"""商家订单只读面（W 阶段 Task 3，PRD M1，契约 §8.12.4）。

只读、不调用 LLM：`merchant_id` 只从商家会话解析（R5），响应不含 `buyer_key`，顾客只以
`buyer_alias` 出现（与商家售后列表同一派生函数）。本组没有任何订单写端点。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import get_session_audit_repository, require_merchant_session
from app.api.v2_deps import get_cursor_codec, merchant_cursor_scope
from app.core.errors import InvalidCursorError, error_responses
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.repositories.audit import AuditRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.trade import (
    FulfillmentStatus,
    MerchantOrderDetailResponse,
    MerchantOrderSummary,
    OrderAfterSaleProjection,
    PaymentStatus,
)
from app.services.v2.cursor import CursorCodec, descending
from app.services.v2.merchant_orders import (
    list_merchant_orders,
    order_page_anchor,
    require_owned_merchant_order,
    to_merchant_order_detail,
    to_merchant_order_summary,
)
from app.services.v2.orders import last_event_times, order_items, order_leads, sort_timestamp

router = APIRouter(prefix="/v2/merchant/orders", tags=["v2-merchant-orders"])


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


@router.get(
    "",
    response_model=CursorPage[MerchantOrderSummary],
    responses=error_responses(401, 403, 422, 503),
)
async def list_orders(
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    payment_status: PaymentStatus | None = None,
    fulfillment_status: FulfillmentStatus | None = None,
    after_sale_status: OrderAfterSaleProjection | None = None,
) -> CursorPage[MerchantOrderSummary]:
    """仅本店具备 v2 交易投影的订单；三项筛选均可选，游标绑定筛选（§8.7.4）。"""

    scope = merchant_cursor_scope(
        ctx,
        endpoint="merchant.orders.list",
        resource="ORDER",
        filters={
            "payment_status": payment_status.value if payment_status else None,
            "fulfillment_status": fulfillment_status.value if fulfillment_status else None,
            "after_sale_status": after_sale_status.value if after_sale_status else None,
        },
        locale=locale,
        limit=limit,
        secret=secret,
    )
    now = datetime.now(UTC)
    try:
        anchor = order_page_anchor(codec.decode(cursor, scope, now=now)) if cursor else None
        rows = await list_merchant_orders(
            session,
            ctx.merchant_id,
            limit=limit,
            anchor=anchor,
            payment_status=payment_status.value if payment_status else None,
            fulfillment_status=fulfillment_status.value if fulfillment_status else None,
            after_sale_status=after_sale_status.value if after_sale_status else None,
        )
        page = codec.page(
            rows,
            key=lambda row: (
                descending(sort_timestamp(row[0].placed_at)),
                descending(str(row[0].id)),
            ),
            scope=scope,
            cursor=None,  # 已校验并在 SQL 层按锚点筛选，只负责签发下一页游标。
            now=now,
        )
    except InvalidCursorError:
        await audits.record_event(
            merchant_id=ctx.merchant_id,
            event_type="INVALID_CURSOR",
            resource_type="order",
            request_id=_request_id(request),
            metadata={"endpoint": scope.endpoint},
        )
        raise

    # 只对分页后的当前页批量取首件商品与最近事件时间，避免全量查询。
    page_orders = [order for order, _, _ in page.items]
    leads = await order_leads(session, page_orders)
    last_events = await last_event_times(session, page_orders)
    return CursorPage[MerchantOrderSummary](
        items=[
            to_merchant_order_summary(
                order,
                item_count=item_count,
                lead_item=leads[order.id],
                last_event_at=last_events[order.id],
                line_count=line_count,
                alias_secret=secret,
                locale=locale,
            )
            for order, item_count, line_count in page.items
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/{order_id}",
    response_model=MerchantOrderDetailResponse,
    responses=error_responses(401, 403, 422, 503),
)
async def get_order(
    order_id: str,
    request: Request,
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audits: Annotated[AuditRepository, Depends(get_session_audit_repository)],
    secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> MerchantOrderDetailResponse:
    """不存在、他店订单与历史（非 v2）订单统一 403 RESOURCE_FORBIDDEN；不写查看审计。"""

    order = await require_owned_merchant_order(
        session, ctx=ctx, order_id=order_id, audits=audits, request_id=_request_id(request)
    )
    leads = await order_leads(session, [order])
    last_events = await last_event_times(session, [order])
    return to_merchant_order_detail(
        order,
        await order_items(session, order.id),
        lead_image_url=leads[order.id].image_url,
        last_event_at=last_events[order.id],
        alias_secret=secret,
        locale=locale,
    )
