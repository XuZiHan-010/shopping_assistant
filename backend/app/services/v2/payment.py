"""模拟支付、顾客取消与超时关闭的竞争裁决（PRD C4、§7.1 不变量 4，契约 §8.10.2）。

三条路径用**同一种**条件更新抢 `payment_status = 'PENDING'`，影响行数为 1 者胜，
胜者在同一事务里完成库存动作与事件；败者 409 ILLEGAL_STATE_TRANSITION，`details` 只含当前支付状态。

| 胜者 | 库存动作 | 事件 |
| --- | --- | --- |
| 支付 | 占用 −q，在库 −q（占用转实扣） | 履约 `PAYMENT_CONFIRMED`；库存 `PAYMENT_DEDUCT` |
| 取消 / 超时 | 占用 −q（释放） | 履约 `ORDER_CLOSED`；库存 `RESERVATION_RELEASE` |

`ORDER_CLOSED` 载荷带存储值 `close_reason`，供 `rebuild_projections` 重算投影。

**支付自己检查 30 分钟截止**（`placed_at > now − 30min`）：Cron 最小间隔是分钟级且不保证准时，
若支付只看 `PENDING`，第 33 分钟的订单仍能付款。
Cron 只负责释放占用（清理），不负责判定超时（正确性）。
历史 `LEGACY_V1` 订单按不存在处理，与越权同一个 403。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from hashlib import sha256
from typing import Any, Final, Literal, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import IllegalStateTransitionError
from app.core.session import SessionContext
from app.domain.order_status_mapping import to_legacy_status
from app.models.analytics import Order, OrderItem, Product
from app.models.events import FulfillmentEvent, InventoryEvent
from app.repositories.protocols import AuditRepositoryProtocol
from app.repositories.v2.idempotency import IdempotencyRepository
from app.schemas.v2.trade import IllegalTransitionDetail, PaymentStatus
from app.services.v2.idempotency import run_idempotent
from app.services.v2.orders import (
    PAYMENT_WINDOW,
    V2_ORIGIN,
    order_items,
    order_uuid,
    owned_order_filter,
    require_owned_order,
    to_order_detail,
)

PAY_OPERATION: Final = "shop.orders.pay"
CANCEL_OPERATION: Final = "shop.orders.cancel"
PAYMENT_CONFIRMED: Final = "PAYMENT_CONFIRMED"
ORDER_CLOSED: Final = "ORDER_CLOSED"
PAYMENT_DEDUCT: Final = "PAYMENT_DEDUCT"
RESERVATION_RELEASE: Final = "RESERVATION_RELEASE"
StoredCloseReason = Literal["CUSTOMER_CANCEL", "TIMEOUT"]


# --- 截止自检 ------------------------------------------------------------------------


async def expire_if_due(
    session: AsyncSession, *, ctx: SessionContext, order_id: str, now: datetime
) -> bool:
    """业务路径的超时自检：本人待支付订单已过 `pay_by` 就在这里关闭并释放占用。

    返回 True 时调用方应先提交，再继续走支付 / 取消——后续请求会因为订单已关闭而得到 409，
    而这次关闭不能随那个 409 一起回滚。不属于本人的订单什么也不做（之后的归属检查统一 403）。
    """

    target = order_uuid(order_id)
    if target is None:
        return False
    order = (
        await session.execute(select(Order).where(*owned_order_filter(ctx, target)))
    ).scalar_one_or_none()
    if order is None or order.payment_status != PaymentStatus.PENDING.value:
        return False
    if now < order.placed_at + PAYMENT_WINDOW:
        return False
    return await close_order(
        session, merchant_id=ctx.merchant_id, order_id=target, reason="TIMEOUT", now=now
    )


# --- 支付与取消 ----------------------------------------------------------------------


async def pay_order(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    order_id: str,
    client_request_id: str,
    principal_secret: bytes,
    audits: AuditRepositoryProtocol,
    request_id: str,
    now: datetime,
) -> dict[str, Any]:
    """模拟支付；同一 `client_request_id` 重放第一次的结果（§8.7.3）。"""

    async def execute() -> dict[str, Any]:
        order = await require_owned_order(
            session, ctx=ctx, order_id=order_id, audits=audits, request_id=request_id
        )
        items = await order_items(session, order.id)
        won = await _conditional_update(
            session,
            order,
            extra=(Order.placed_at > now - PAYMENT_WINDOW,),
            values={
                "payment_status": PaymentStatus.PAID.value,
                "order_status": to_legacy_status("PAID", "NOT_SHIPPED", None),
                "paid_at": now,
                "paid_amount": Order.total_amount,
            },
        )
        if not won:
            raise await _illegal(session, order)
        for item in _lock_order(items):
            # 占用转实扣：两列同一条语句更新，`ck_products_reserved_le_on_hand` 始终成立。
            await session.execute(
                update(Product)
                .where(Product.id == item.product_id)
                .values(
                    stock_reserved=Product.stock_reserved - item.quantity,
                    stock_on_hand=Product.stock_on_hand - item.quantity,
                )
            )
        _record_events(
            session, order, items, fulfillment=PAYMENT_CONFIRMED, inventory=PAYMENT_DEDUCT, now=now
        )
        await session.flush()
        return await _detail(session, order, items)

    return await _idempotent(
        session, ctx, principal_secret, PAY_OPERATION, client_request_id, order_id, execute
    )


async def cancel_order(
    session: AsyncSession,
    *,
    ctx: SessionContext,
    order_id: str,
    client_request_id: str,
    principal_secret: bytes,
    audits: AuditRepositoryProtocol,
    request_id: str,
    now: datetime,
) -> dict[str, Any]:
    """顾客取消：仅 `PENDING` 可取消，成功释放占用。"""

    async def execute() -> dict[str, Any]:
        order = await require_owned_order(
            session, ctx=ctx, order_id=order_id, audits=audits, request_id=request_id
        )
        if not await close_order(
            session,
            merchant_id=ctx.merchant_id,
            order_id=order.id,
            reason="CUSTOMER_CANCEL",
            now=now,
        ):
            raise await _illegal(session, order)
        items = await order_items(session, order.id)
        return await _detail(session, order, items)

    return await _idempotent(
        session, ctx, principal_secret, CANCEL_OPERATION, client_request_id, order_id, execute
    )


async def close_order(
    session: AsyncSession,
    *,
    merchant_id: UUID,
    order_id: UUID,
    reason: StoredCloseReason,
    now: datetime,
) -> bool:
    """取消与超时关闭共用：抢到 `PENDING → CLOSED` 才释放占用、写事件，返回是否抢到。

    超时关闭在条件里再核一次截止时间，防止任务拿着过期的候选列表关掉刚好还能付款的订单。
    """

    extra: tuple[Any, ...] = ()
    if reason == "TIMEOUT":
        extra = (Order.placed_at <= now - PAYMENT_WINDOW,)
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(Order)
            .where(
                Order.id == order_id,
                Order.merchant_id == merchant_id,
                Order.lifecycle_origin == V2_ORIGIN,
                Order.payment_status == PaymentStatus.PENDING.value,
                *extra,
            )
            .values(
                payment_status=PaymentStatus.CLOSED.value,
                order_status=to_legacy_status("CLOSED", "NOT_SHIPPED", reason),
                close_reason=reason,
                closed_at=now,
            )
            .returning(Order.id)
        ),
    )
    if result.first() is None:
        return False
    order = await session.get(Order, order_id, populate_existing=True)
    assert order is not None
    items = await order_items(session, order_id)
    for item in _lock_order(items):
        await session.execute(
            update(Product)
            .where(Product.id == item.product_id)
            .values(stock_reserved=Product.stock_reserved - item.quantity)
        )
    _record_events(
        session,
        order,
        items,
        fulfillment=ORDER_CLOSED,
        inventory=RESERVATION_RELEASE,
        now=now,
        fulfillment_payload={"close_reason": reason},
    )
    await session.flush()
    return True


# --- 共用 ----------------------------------------------------------------------------


def _lock_order(items: list[OrderItem]) -> list[OrderItem]:
    """按商品 ID 顺序更新库存行，与结账占库同一顺序：两单以相反顺序含同两件商品时不会死锁。"""

    return sorted(items, key=lambda item: str(item.product_id))


async def _conditional_update(
    session: AsyncSession, order: Order, *, extra: tuple[Any, ...], values: dict[str, Any]
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(Order)
            .where(
                Order.id == order.id,
                Order.merchant_id == order.merchant_id,
                Order.payment_status == PaymentStatus.PENDING.value,
                *extra,
            )
            .values(**values)
            .returning(Order.id)
        ),
    )
    return result.first() is not None


async def _illegal(session: AsyncSession, order: Order) -> IllegalStateTransitionError:
    """败者重读当前支付状态；`details` 只含这一项，不含锁、版本或内部状态。"""

    await session.refresh(order)
    detail = IllegalTransitionDetail(payment_status=PaymentStatus(order.payment_status))
    return IllegalStateTransitionError(details=[detail.model_dump(mode="json")])


def _record_events(
    session: AsyncSession,
    order: Order,
    items: list[OrderItem],
    *,
    fulfillment: str,
    inventory: str,
    now: datetime,
    fulfillment_payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        FulfillmentEvent(
            merchant_id=order.merchant_id,
            subject_id=order.id,
            event_type=fulfillment,
            occurred_at=now,
            dedupe_key=f"{fulfillment}:{order.id}",
            payload={"origin": V2_ORIGIN, **(fulfillment_payload or {})},
        )
    )
    session.add_all(
        InventoryEvent(
            merchant_id=order.merchant_id,
            subject_id=item.product_id,
            event_type=inventory,
            occurred_at=now,
            dedupe_key=f"{inventory}:{order.id}:{item.product_id}",
            payload={"order_id": str(order.id), "quantity": item.quantity},
        )
        for item in items
    )


async def _detail(session: AsyncSession, order: Order, items: list[OrderItem]) -> dict[str, Any]:
    await session.refresh(order)
    return to_order_detail(order, items).model_dump(mode="json")


async def _idempotent(
    session: AsyncSession,
    ctx: SessionContext,
    principal_secret: bytes,
    operation: str,
    client_request_id: str,
    order_id: str,
    execute: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    return await run_idempotent(
        repo=IdempotencyRepository(session),
        ctx=ctx,
        secret=principal_secret,
        operation=operation,
        client_request_id=client_request_id,
        request_digest=sha256(f"{operation}\u0000{order_id}".encode()).hexdigest(),
        response_status=200,
        execute=execute,
    )
