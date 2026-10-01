"""商家订单只读面（W 阶段 Task 3，契约 §8.12.4）：`GET /api/v2/merchant/orders` 与详情。

只读、按 `merchant_id` 隔离；顾客以店铺级脱敏别名 `buyer_alias` 出现，绝不下发 `buyer_key`。
只覆盖具备 v2 交易投影的订单（`lifecycle_origin == V2_ORIGIN`）；越权、不存在与历史订单统一走
`require_owned` 的 403 路径，与顾客端 `require_owned_order` 同一判定逻辑。摘要与详情的字段构造
全部复用 `services/v2/orders.py`，本模块只负责商家侧的过滤、归属校验与 `buyer_alias` 拼接。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InvalidCursorError
from app.core.session import SessionContext, buyer_alias
from app.localization.locales import SupportedLocale
from app.models.analytics import Order, OrderItem
from app.repositories.protocols import AuditRepositoryProtocol
from app.schemas.v2.trade import (
    MerchantOrderDetailResponse,
    MerchantOrderSummary,
    OrderLeadItem,
)
from app.services.resource_scope import ScopeLookupResult, require_owned
from app.services.v2.cursor import descending
from app.services.v2.orders import (
    V2_ORIGIN,
    order_uuid,
    to_order_detail,
    to_order_summary,
)


def order_page_anchor(key: tuple[str, ...]) -> tuple[datetime, UUID]:
    """还原既有游标中的降序键；无须探测锚点订单是否仍存在。"""
    try:
        timestamp, order_id = key
        moment = datetime.strptime(descending(timestamp), "%Y-%m-%dT%H:%M:%S.%f")
        return moment.replace(tzinfo=UTC), UUID(descending(order_id))
    except (ValueError, TypeError) as exc:
        raise InvalidCursorError from exc


def merchant_order_filters(
    merchant_id: UUID,
    *,
    payment_status: str | None = None,
    fulfillment_status: str | None = None,
    after_sale_status: str | None = None,
) -> tuple[Any, ...]:
    """本店 + v2 交易投影的固定过滤，三项筛选均为可选且默认不过滤。"""

    clauses: list[Any] = [Order.merchant_id == merchant_id, Order.lifecycle_origin == V2_ORIGIN]
    if payment_status is not None:
        clauses.append(Order.payment_status == payment_status)
    if fulfillment_status is not None:
        clauses.append(Order.fulfillment_status == fulfillment_status)
    if after_sale_status is not None:
        clauses.append(Order.after_sale_status == after_sale_status)
    return tuple(clauses)


async def list_merchant_orders(
    session: AsyncSession,
    merchant_id: UUID,
    *,
    limit: int,
    anchor: tuple[datetime, UUID] | None = None,
    payment_status: str | None = None,
    fulfillment_status: str | None = None,
    after_sale_status: str | None = None,
) -> list[tuple[Order, int, int]]:
    """本店 v2 订单、件数（`item_count`）与行数（`line_count`），排序 `created_at DESC, id DESC`。

    件数是各行数量之和，行数是订单行条数——两者语义不同：一行数量 3 件是 `item_count=3`
    但 `line_count=1`。同一子查询里一并算出，避免为行数再单独发一轮查询。
    """

    clauses = list(merchant_order_filters(
        merchant_id,
        payment_status=payment_status,
        fulfillment_status=fulfillment_status,
        after_sale_status=after_sale_status,
    ))
    if anchor is not None:
        clauses.append(
            tuple_(Order.placed_at, Order.id) < tuple_(literal(anchor[0]), literal(anchor[1]))
        )
    # 先取有明细的订单窗口，避免全店聚合/读取；多一行仅用于判断 has_more。
    orders = list((await session.scalars(
        select(Order)
        .where(
            *clauses,
            select(OrderItem.id).where(
                OrderItem.order_id == Order.id,
                OrderItem.merchant_id == merchant_id,
            ).exists(),
        )
        .order_by(Order.placed_at.desc(), Order.id.desc())
        .limit(limit + 1)
    )).all())
    if not orders:
        return []
    counts = await session.execute(
        select(
            OrderItem.order_id,
            func.sum(OrderItem.quantity).label("item_count"),
            func.count(OrderItem.id).label("line_count"),
        )
        .where(
            OrderItem.merchant_id == merchant_id,
            OrderItem.order_id.in_([order.id for order in orders]),
        )
        .group_by(OrderItem.order_id)
    )
    by_id = {order_id: (int(items), int(lines)) for order_id, items, lines in counts.tuples()}
    return [
        (order, *by_id[order.id]) for order in orders if order.id in by_id
    ]


async def require_owned_merchant_order(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    order_id: str,
    audits: AuditRepositoryProtocol,
    request_id: str,
) -> Order:
    """商家侧订单归属：不存在、他店订单、历史（非 v2）订单与非法标识对外同一个 403。"""

    async def fetch() -> ScopeLookupResult[Order]:
        target = order_uuid(order_id)
        if target is None:
            return ScopeLookupResult(resource=None, target_exists=None)
        order = (
            await session.execute(
                select(Order)
                .where(Order.id == target, *merchant_order_filters(ctx.merchant_id))
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return ScopeLookupResult(resource=order, target_exists=None)

    return await require_owned(
        fetch,
        ctx=ctx,
        audits=audits,
        resource_type="order",
        resource_id=order_id,
        request_id=request_id,
    )


def to_merchant_order_summary(
    order: Order,
    *,
    item_count: int,
    lead_item: OrderLeadItem,
    last_event_at: datetime,
    line_count: int,
    alias_secret: bytes,
    locale: SupportedLocale,
) -> MerchantOrderSummary:
    summary = to_order_summary(
        order, item_count=item_count, lead_item=lead_item, last_event_at=last_event_at
    )
    return MerchantOrderSummary(
        **summary.model_dump(),
        buyer_alias=buyer_alias(alias_secret, order.merchant_id, order.buyer_key, locale),
        line_count=line_count,
    )


def to_merchant_order_detail(
    order: Order,
    items: Sequence[OrderItem],
    *,
    lead_image_url: str | None,
    last_event_at: datetime,
    alias_secret: bytes,
    locale: SupportedLocale,
) -> MerchantOrderDetailResponse:
    detail = to_order_detail(
        order, items, lead_image_url=lead_image_url, last_event_at=last_event_at
    )
    return MerchantOrderDetailResponse(
        **detail.model_dump(),
        buyer_alias=buyer_alias(alias_secret, order.merchant_id, order.buyer_key, locale),
    )
