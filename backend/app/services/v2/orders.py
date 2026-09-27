"""v2 订单 ORM → 顾客端契约（§8.10.1）的唯一出口，供下单、支付、取消、列表与详情共用。

三维状态分列返回（D14⑥）；关闭原因在这里由存储词汇换成 API 词汇，存储值不直接下发。
金额在库内是 `Decimal` 元，这里一律换成整数分（§8.7.8）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionContext
from app.domain.order_status_mapping import close_reason_to_api
from app.models.analytics import Order, OrderItem
from app.models.events import FulfillmentEvent
from app.repositories.protocols import AuditRepositoryProtocol
from app.schemas.v2.common import yuan_to_cents
from app.schemas.v2.trade import (
    CloseReason,
    FulfillmentEventType,
    FulfillmentStatus,
    OrderAfterSaleProjection,
    OrderDetailResponse,
    OrderItemPriceSnapshot,
    OrderSummary,
    PaymentStatus,
)
from app.schemas.v2.trade import FulfillmentEvent as FulfillmentEventOut
from app.services.resource_scope import ScopeLookupResult, require_owned

#: PRD §7.1：30 分钟未支付关闭。支付路径自己按它判定超时，Cron 只做清理。
PAYMENT_WINDOW: Final = timedelta(minutes=30)
V2_ORIGIN: Final = "V2"
SOURCE_TIMEZONE: Final = "Asia/Shanghai"


def pay_by(order: Order) -> datetime:
    return order.placed_at + PAYMENT_WINDOW


def to_order_summary(order: Order, *, item_count: int) -> OrderSummary:
    return OrderSummary(
        id=str(order.id),
        payment_status=PaymentStatus(order.payment_status),
        fulfillment_status=FulfillmentStatus(order.fulfillment_status),
        after_sale_status=OrderAfterSaleProjection(order.after_sale_status),
        total_cents=yuan_to_cents(order.total_amount),
        item_count=item_count,
        created_at=order.placed_at,
        pay_by=pay_by(order),
    )


def to_order_detail(order: Order, items: Sequence[OrderItem]) -> OrderDetailResponse:
    snapshots = [
        OrderItemPriceSnapshot(
            order_item_id=str(item.id),
            product_id=str(item.product_id),
            name=item.title_snapshot or "—",
            quantity=item.quantity,
            unit_price_cents=yuan_to_cents(item.unit_price),
            discount_cents=yuan_to_cents(item.discount_amount),
            line_total_cents=yuan_to_cents(item.line_total),
        )
        for item in items
    ]
    close_reason = close_reason_to_api(order.close_reason)
    summary = to_order_summary(order, item_count=sum(item.quantity for item in items))
    return OrderDetailResponse(
        **summary.model_dump(),
        items=snapshots,
        subtotal_cents=sum(s.unit_price_cents * s.quantity for s in snapshots),
        discount_cents=sum(s.discount_cents for s in snapshots),
        coupon_id=str(order.coupon_id) if order.coupon_id is not None else None,
        paid_at=order.paid_at,
        closed_at=order.closed_at,
        close_reason=CloseReason(close_reason) if close_reason is not None else None,
        is_demo=True,
    )


# --- 归属 --------------------------------------------------------------------------


def order_uuid(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except ValueError:
        return None


def owned_order_filter(ctx: SessionContext, order_id: UUID) -> tuple[Any, ...]:
    """商家 + 顾客双重过滤（D7①），并只认 v2 订单；历史订单与越权同一结果。"""

    assert ctx.buyer_key is not None, "订单端点要求已绑定顾客，由路由依赖保证"
    return (
        Order.id == order_id,
        Order.merchant_id == ctx.merchant_id,
        Order.buyer_key == ctx.buyer_key,
        Order.lifecycle_origin == V2_ORIGIN,
    )


async def require_owned_order(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    order_id: str,
    audits: AuditRepositoryProtocol,
    request_id: str,
) -> Order:
    """一次固定形状查询定生死：不存在、非本人、别家店、历史订单、非法标识对外同一个 403。"""

    async def fetch() -> ScopeLookupResult[Order]:
        target = order_uuid(order_id)
        if target is None:
            return ScopeLookupResult(resource=None, target_exists=None)
        order = (
            await session.execute(
                select(Order)
                .where(*owned_order_filter(ctx, target))
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


async def order_items(session: AsyncSession, order_id: UUID) -> list[OrderItem]:
    result = await session.scalars(
        select(OrderItem)
        .where(OrderItem.order_id == order_id)
        .order_by(OrderItem.created_at, OrderItem.id)
    )
    return list(result.all())


# --- 列表与履约事件 ------------------------------------------------------------------


def sort_timestamp(moment: datetime) -> str:
    """游标排序键里的时刻：固定宽度的 UTC 文本，字符串比较与时间先后一致。

    不用 `isoformat()`：微秒为 0 时它会省掉小数部分，`"…:00+00:00"` 与 `"…:00.5+00:00"`
    的字典序就和时间先后对不上了。
    """

    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


async def list_owned_orders(session: AsyncSession, ctx: SessionContext) -> list[tuple[Order, int]]:
    """本人本店的 v2 订单与件数，契约排序 `created_at DESC, id DESC`（下单时刻即 `placed_at`）。"""

    assert ctx.buyer_key is not None, "订单端点要求已绑定顾客，由路由依赖保证"
    counts = (
        select(OrderItem.order_id, func.sum(OrderItem.quantity).label("item_count"))
        .group_by(OrderItem.order_id)
        .subquery()
    )
    result = await session.execute(
        select(Order, counts.c.item_count)
        .join(counts, counts.c.order_id == Order.id)
        .where(
            Order.merchant_id == ctx.merchant_id,
            Order.buyer_key == ctx.buyer_key,
            Order.lifecycle_origin == V2_ORIGIN,
        )
        .order_by(Order.placed_at.desc(), Order.id.desc())
    )
    return [(order, int(count)) for order, count in result.tuples().all()]


async def fulfillment_events(session: AsyncSession, order: Order) -> list[FulfillmentEventOut]:
    """契约排序 `occurred_at ASC, id ASC`；时刻 UTC，另给来源时区，换算交给前端（D14⑩）。"""

    rows = await session.scalars(
        select(FulfillmentEvent)
        .where(
            FulfillmentEvent.merchant_id == order.merchant_id,
            FulfillmentEvent.subject_id == order.id,
        )
        .order_by(FulfillmentEvent.occurred_at, FulfillmentEvent.id)
    )
    return [
        FulfillmentEventOut(
            id=str(event.id),
            event_type=FulfillmentEventType(event.event_type),
            occurred_at=event.occurred_at,
            source_timezone=str(event.payload.get("source_timezone") or order.source_timezone),
        )
        for event in rows.all()
    ]
