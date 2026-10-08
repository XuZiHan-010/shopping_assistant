"""售后状态迁移：先确定合法动作与系统续跳，再由同一事务写投影和事件。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.after_sales import AfterSale
from app.models.analytics import Order
from app.models.events import AfterSaleEvent
from app.schemas.v2.after_sales import (
    AfterSaleActor,
    AfterSaleState,
    AfterSaleType,
    is_allowed_transition,
)

S = AfterSaleState
A = AfterSaleActor
K = AfterSaleType

_ACTORS: dict[tuple[S | None, S], A] = {
    (None, S.PENDING_MERCHANT): A.CUSTOMER,
    (S.PENDING_MERCHANT, S.APPROVED): A.MERCHANT,
    (S.PENDING_MERCHANT, S.REJECTED): A.MERCHANT,
    (S.PENDING_MERCHANT, S.AWAITING_CUSTOMER_INFO): A.MERCHANT,
    (S.AWAITING_CUSTOMER_INFO, S.PENDING_MERCHANT): A.CUSTOMER,
    (S.APPROVED, S.AWAITING_RETURN): A.SYSTEM,
    (S.APPROVED, S.REFUNDED): A.MERCHANT,
    (S.AWAITING_RETURN, S.RECEIVED): A.MERCHANT,
    (S.RECEIVED, S.REFUNDED): A.MERCHANT,
    (S.REFUNDED, S.CLOSED): A.SYSTEM,
    (S.REJECTED, S.CLOSED): A.SYSTEM,
    (S.APPROVED, S.CLOSED): A.SYSTEM,
}


class IllegalTransition(ValueError):
    """类型、状态、触发方或次数不允许该迁移。"""


def plan_transition(
    kind: K,
    source: S | None,
    target: S,
    *,
    actor: A,
    prior_information_requests: int | None = None,
) -> list[tuple[S, A]]:
    """外部只可请求顾客或商家动作；系统续跳只能由这里自动生成。"""

    expected_actor = _ACTORS.get((source, target))
    if actor == A.SYSTEM or expected_actor != actor:
        raise IllegalTransition("售后迁移触发方不匹配")
    if not is_allowed_transition(
        kind, source, target, prior_information_requests=prior_information_requests
    ):
        raise IllegalTransition("售后状态迁移不合法")

    hops: list[tuple[S, A]] = [(target, actor)]
    follow_on: S | None = None
    if target == S.APPROVED and kind == K.RETURN_REFUND:
        follow_on = S.AWAITING_RETURN
    elif (target == S.APPROVED and kind == K.TICKET) or target in {S.REJECTED, S.REFUNDED}:
        follow_on = S.CLOSED
    if follow_on is not None:
        if not is_allowed_transition(kind, target, follow_on):
            raise IllegalTransition("系统续跳不合法")
        hops.append((follow_on, A.SYSTEM))
    return hops


async def transition(
    session: AsyncSession,
    *,
    merchant_id: UUID,
    after_sale_id: UUID,
    target: S,
    actor: A,
    now: datetime,
) -> AfterSale:
    """锁定售后主记录，在当前事务内追加所有事件并更新查询投影。调用方负责提交。"""

    record = (
        await session.execute(
            select(AfterSale)
            .where(AfterSale.id == after_sale_id, AfterSale.merchant_id == merchant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if record is None:
        raise IllegalTransition("售后事项不可用")
    prior_requests = int(
        await session.scalar(
            select(func.count())
            .select_from(AfterSaleEvent)
            .where(
                AfterSaleEvent.merchant_id == merchant_id,
                AfterSaleEvent.subject_id == after_sale_id,
                AfterSaleEvent.event_type == S.AWAITING_CUSTOMER_INFO.value,
            )
        )
        or 0
    )
    hops = plan_transition(
        K(record.after_sale_type),
        S(record.state),
        target,
        actor=actor,
        prior_information_requests=prior_requests,
    )
    latest = await session.scalar(
        select(func.max(AfterSaleEvent.occurred_at)).where(
            AfterSaleEvent.merchant_id == merchant_id,
            AfterSaleEvent.subject_id == after_sale_id,
        )
    )
    moment = now.astimezone(UTC)
    if latest is not None:
        moment = max(moment, latest.astimezone(UTC) + timedelta(microseconds=1))
    source = S(record.state)
    for next_state, next_actor in hops:
        record.state_version += 1
        session.add(
            AfterSaleEvent(
                merchant_id=merchant_id,
                subject_id=after_sale_id,
                event_type=next_state.value,
                occurred_at=moment,
                dedupe_key=f"after-sale:{after_sale_id}:{record.state_version}",
                payload={
                    "from_state": source.value,
                    "to_state": next_state.value,
                    "actor": next_actor.value,
                },
            )
        )
        source = next_state
        moment += timedelta(microseconds=1)
    record.state = source.value
    order = (
        await session.execute(
            select(Order)
            .where(Order.id == record.order_id, Order.merchant_id == merchant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    order.after_sale_status = "CLOSED" if source == S.CLOSED else "ACTIVE"
    await session.flush()
    return record
