"""由事件账本重算订单投影，仅报告漂移，不自动修复。"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_config import JobSettings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.domain.order_status_mapping import to_legacy_status
from app.models.analytics import Order
from app.models.events import AfterSaleEvent, FulfillmentEvent


@dataclass(frozen=True)
class ProjectionDrift:
    order_id: UUID
    field: str
    actual: str | None
    expected: str | None


@dataclass(frozen=True)
class ProjectionReport:
    checked: int
    mismatches: int
    drift: tuple[ProjectionDrift, ...]


_LEGACY_STAGE = {
    "ORDER_PLACED": 0,
    "PAYMENT_CONFIRMED": 1,
    "SHIPPED": 2,
    "IN_TRANSIT": 3,
    "OUT_FOR_DELIVERY": 4,
    "DELIVERED": 5,
    "ORDER_CLOSED": 6,
}
_FULFILLMENT_EVENTS = {"SHIPPED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED"}


def _expected(events: list[FulfillmentEvent]) -> tuple[str, str, str | None]:
    if not events:
        raise ValueError("订单缺少履约锚事件")
    legacy = all(e.payload.get("origin") == "LEGACY_V1_BACKFILL" for e in events)
    if legacy:
        # 历史 paid_at 可能早于 placed_at；必须按状态阶段而非伪时间排序。
        ordered = sorted(events, key=lambda e: (_LEGACY_STAGE.get(e.event_type, 99), e.dedupe_key))
    else:
        ordered = sorted(events, key=lambda e: (e.occurred_at, e.created_at, e.dedupe_key))
    payment = "PENDING"
    fulfillment = "NOT_SHIPPED"
    reason = None
    for event in ordered:
        if event.event_type == "ORDER_PLACED":
            continue
        if event.event_type == "PAYMENT_CONFIRMED":
            payment = "PAID"
        elif event.event_type in _FULFILLMENT_EVENTS:
            fulfillment = event.event_type
        elif event.event_type == "ORDER_CLOSED":
            payment = "CLOSED"
            fulfillment = "NOT_SHIPPED"
            reason = event.payload.get("close_reason")
        else:
            raise ValueError(f"未知履约事件：{event.event_type}")
    return payment, fulfillment, reason


async def rebuild_projections(
    db: AsyncSession, *, dry_run: bool = True, merchant_id: UUID | None = None
) -> ProjectionReport:
    """检查 event truth 与 orders 查询投影；即使 dry_run=False 也不覆写漂移。"""
    del dry_run  # 保留调用兼容形状；自动覆盖会掩盖写路径 bug。
    orders_stmt = select(Order)
    events_stmt = select(FulfillmentEvent)
    after_stmt = select(AfterSaleEvent)
    if merchant_id is not None:
        orders_stmt = orders_stmt.where(Order.merchant_id == merchant_id)
        events_stmt = events_stmt.where(FulfillmentEvent.merchant_id == merchant_id)
        after_stmt = after_stmt.where(AfterSaleEvent.merchant_id == merchant_id)
    orders = (await db.scalars(orders_stmt)).all()
    events = (await db.scalars(events_stmt)).all()
    after_events = (await db.scalars(after_stmt)).all()
    by_order: dict[tuple[UUID, UUID], list[FulfillmentEvent]] = {}
    for event in events:
        by_order.setdefault((event.merchant_id, event.subject_id), []).append(event)
    after_by_order: dict[tuple[UUID, UUID], list[AfterSaleEvent]] = {}
    for after_event in after_events:
        raw_id = after_event.payload.get("order_id")
        if raw_id:
            key = (after_event.merchant_id, UUID(str(raw_id)))
            after_by_order.setdefault(key, []).append(after_event)

    drifts: list[ProjectionDrift] = []
    for order in orders:
        key = (order.merchant_id, order.id)
        try:
            payment, fulfillment, reason = _expected(by_order.get(key, []))
            legacy = to_legacy_status(payment, fulfillment, reason)
        except ValueError as exc:
            drifts.append(ProjectionDrift(order.id, "events", None, str(exc)))
            continue
        order_after_events = sorted(
            after_by_order.get(key, []), key=lambda e: (e.occurred_at, e.created_at, e.dedupe_key)
        )
        after_status = "NONE"
        if order_after_events:
            last = order_after_events[-1]
            after_status = str(last.payload.get("after_sale_status", last.event_type))
        expected = {
            "payment_status": payment,
            "fulfillment_status": fulfillment,
            "close_reason": reason,
            "after_sale_status": after_status,
            "order_status": legacy,
        }
        for field, value in expected.items():
            actual = getattr(order, field)
            if actual != value:
                drifts.append(ProjectionDrift(order.id, field, actual, value))
    return ProjectionReport(len(orders), len({drift.order_id for drift in drifts}), tuple(drifts))


async def _run_cli(merchant_id: UUID | None) -> ProjectionReport:
    database = Database(JobSettings())
    try:
        async with database.session() as session:
            return await rebuild_projections(session, dry_run=True, merchant_id=merchant_id)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="检查订单投影与事件账本的一致性")
    parser.add_argument("--dry-run", action="store_true", required=True, help="只报告漂移")
    parser.add_argument("--merchant-id", type=UUID, help="只检查指定商家")
    args = parser.parse_args()
    configure_event_loop_policy()
    report = asyncio.run(_run_cli(args.merchant_id))
    print(f"checked={report.checked} mismatches={report.mismatches}")
    for drift in report.drift:
        print(
            f"order={drift.order_id} field={drift.field} "
            f"actual={drift.actual} expected={drift.expected}"
        )
    if report.mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
