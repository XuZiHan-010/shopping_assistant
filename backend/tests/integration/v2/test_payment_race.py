"""模拟支付与超时关闭的竞争（交易计划 Task 4，PRD §7.1 不变量 4，契约 §8.10.2）——真实 PostgreSQL。

支付、顾客取消、超时关闭用同一个条件更新抢 `payment_status = 'PENDING'`，影响行数为 1 者胜；
胜者在同一事务里完成库存动作与事件。支付自己检查 30 分钟截止：正确性不依赖 Cron 调度精度。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI

from app.core.errors import AppError, IllegalStateTransitionError
from app.db.session import Database
from app.jobs.close_expired_orders import close_expired_orders
from app.jobs.rebuild_projections import rebuild_projections
from app.services.v2.checkout import place_order
from app.services.v2.payment import cancel_order, expire_if_due, pay_order
from tests.conftest import MERCHANT_ONE_ID
from tests.support.merchant_v2 import seed_product
from tests.support.trade import (
    PRINCIPAL_SECRET,
    Stock,
    bound_context,
    database_of,
    fulfillment_events,
    get_order,
    inventory_events,
    seed_cart,
    stock,
)

pytestmark = pytest.mark.integration

INITIAL = 10
BUYER = "pay-buyer"
CTX = bound_context(MERCHANT_ONE_ID, BUYER)


class _NoAudit:
    async def record_event(self, **_: Any) -> None:
        return None

    async def record_scope_violation(self, **_: Any) -> None:
        return None


async def _pending_order(
    database: Database, product_id: UUID, *, qty: int, placed_at: datetime, crid: str = "o1"
) -> str:
    await seed_cart(database, MERCHANT_ONE_ID, BUYER, {product_id: qty})
    async with database.session() as session:
        body = await place_order(
            session,
            ctx=CTX,
            coupon_id=None,
            client_request_id=crid,
            principal_secret=PRINCIPAL_SECRET,
            now=placed_at,
        )
        await session.commit()
    return str(body["id"])


async def _pay(
    database: Database, order_id: str, *, now: datetime, crid: str = "p1"
) -> dict[str, Any] | AppError:
    try:
        async with database.session() as session:
            if await expire_if_due(session, ctx=CTX, order_id=order_id, now=now):
                await session.commit()
            body = await pay_order(
                session,
                ctx=CTX,
                order_id=order_id,
                client_request_id=crid,
                principal_secret=PRINCIPAL_SECRET,
                audits=_NoAudit(),
                request_id="t",
                now=now,
            )
            await session.commit()
            return body
    except AppError as error:
        return error


async def _cancel(
    database: Database, order_id: str, *, now: datetime, crid: str = "c1"
) -> dict[str, Any] | AppError:
    try:
        async with database.session() as session:
            body = await cancel_order(
                session,
                ctx=CTX,
                order_id=order_id,
                client_request_id=crid,
                principal_secret=PRINCIPAL_SECRET,
                audits=_NoAudit(),
                request_id="t",
                now=now,
            )
            await session.commit()
            return body
    except AppError as error:
        return error


async def _no_drift(database: Database) -> None:
    async with database.session() as session:
        report = await rebuild_projections(session, merchant_id=MERCHANT_ONE_ID)
    assert report.mismatches == 0, report.drift


@pytest.mark.asyncio
async def test_payment_converts_reservation_into_deduction(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    oid = await _pending_order(database, pid, qty=2, placed_at=now)

    body = await _pay(database, oid, now=now + timedelta(minutes=5))

    assert isinstance(body, dict)
    assert body["payment_status"] == "PAID"
    assert body["paid_at"] is not None
    assert await stock(database, pid) == Stock(on_hand=INITIAL - 2, reserved=0)
    assert await fulfillment_events(database, oid) == ["ORDER_PLACED", "PAYMENT_CONFIRMED"]
    assert await inventory_events(database, pid) == [("ORDER_RESERVE", 2), ("PAYMENT_DEDUCT", 2)]
    order = await get_order(database, oid)
    assert order.order_status == "PAID" and order.paid_amount == order.total_amount
    await _no_drift(database)


@pytest.mark.asyncio
async def test_pay_and_cancel_race_has_one_winner(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    oid = await _pending_order(database, pid, qty=2, placed_at=now)

    results = await asyncio.gather(_pay(database, oid, now=now), _cancel(database, oid, now=now))

    status = (await get_order(database, oid)).payment_status
    assert status in {"PAID", "CLOSED"}
    losers = [r for r in results if isinstance(r, AppError)]
    assert len(losers) == 1 and isinstance(losers[0], IllegalStateTransitionError)
    assert losers[0].details == [{"payment_status": status}]
    s = await stock(database, pid)
    if status == "PAID":
        assert s == Stock(on_hand=INITIAL - 2, reserved=0)
    else:
        assert s == Stock(on_hand=INITIAL, reserved=0)  # 未被重复释放或误扣
    await _no_drift(database)


@pytest.mark.asyncio
async def test_pay_and_timeout_job_race_has_one_winner(postgres_app: FastAPI) -> None:
    """支付端的时钟还差一分钟，任务的时钟已过截止：两边都认为自己有资格，库只让一方生效。"""

    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    placed = datetime.now(UTC) - timedelta(minutes=40)
    oid = await _pending_order(database, pid, qty=2, placed_at=placed)

    await asyncio.gather(
        _pay(database, oid, now=placed + timedelta(minutes=29)),
        close_expired_orders(database, now=placed + timedelta(minutes=31)),
    )

    order = await get_order(database, oid)
    s = await stock(database, pid)
    if order.payment_status == "PAID":
        assert s == Stock(on_hand=INITIAL - 2, reserved=0)
    else:
        assert order.payment_status == "CLOSED" and order.close_reason == "TIMEOUT"
        assert s == Stock(on_hand=INITIAL, reserved=0)
    await _no_drift(database)


@pytest.mark.asyncio
async def test_pay_is_idempotent(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    oid = await _pending_order(database, pid, qty=1, placed_at=now)

    results = [await _pay(database, oid, now=now, crid="p1") for _ in range(3)]

    assert all(isinstance(r, dict) for r in results)
    assert results[0] == results[1] == results[2]
    assert (await stock(database, pid)).on_hand == INITIAL - 1  # 只扣一次


@pytest.mark.asyncio
async def test_second_payment_with_new_request_id_is_illegal(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    oid = await _pending_order(database, pid, qty=1, placed_at=now)
    await _pay(database, oid, now=now, crid="p1")

    again = await _pay(database, oid, now=now, crid="p2")

    assert isinstance(again, IllegalStateTransitionError)
    assert again.details == [{"payment_status": "PAID"}]
    assert (await stock(database, pid)).on_hand == INITIAL - 1


@pytest.mark.asyncio
async def test_payment_after_deadline_fails_even_if_job_has_not_run(postgres_app: FastAPI) -> None:
    """正确性不依赖 Cron 调度精度：第 33 分钟的支付自己判定超时，并顺手关闭、释放。"""

    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    oid = await _pending_order(database, pid, qty=2, placed_at=now - timedelta(minutes=33))

    result = await _pay(database, oid, now=now)

    assert isinstance(result, IllegalStateTransitionError)
    assert result.details == [{"payment_status": "CLOSED"}]
    order = await get_order(database, oid)
    assert order.payment_status == "CLOSED" and order.close_reason == "TIMEOUT"
    assert order.closed_at is not None
    assert await stock(database, pid) == Stock(on_hand=INITIAL, reserved=0)
    assert await fulfillment_events(database, oid) == ["ORDER_PLACED", "ORDER_CLOSED"]
    await _no_drift(database)


@pytest.mark.asyncio
async def test_payment_exactly_at_the_deadline_is_too_late(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    placed = datetime.now(UTC) - timedelta(hours=1)
    oid = await _pending_order(database, pid, qty=1, placed_at=placed)

    result = await _pay(database, oid, now=placed + timedelta(minutes=30))

    assert isinstance(result, IllegalStateTransitionError)


@pytest.mark.asyncio
async def test_cancel_releases_the_reservation(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    oid = await _pending_order(database, pid, qty=3, placed_at=now)

    body = await _cancel(database, oid, now=now)

    assert isinstance(body, dict)
    assert body["payment_status"] == "CLOSED"
    assert body["close_reason"] == "USER_CANCELLED"
    assert (await get_order(database, oid)).close_reason == "CUSTOMER_CANCEL"
    assert await stock(database, pid) == Stock(on_hand=INITIAL, reserved=0)
    assert await inventory_events(database, pid) == [
        ("ORDER_RESERVE", 3),
        ("RESERVATION_RELEASE", 3),
    ]
    await _no_drift(database)


@pytest.mark.asyncio
async def test_paid_order_cannot_be_cancelled(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    oid = await _pending_order(database, pid, qty=1, placed_at=now)
    await _pay(database, oid, now=now)

    result = await _cancel(database, oid, now=now)

    assert isinstance(result, IllegalStateTransitionError)
    assert result.details == [{"payment_status": "PAID"}]


@pytest.mark.asyncio
async def test_close_job_only_touches_orders_older_than_30_minutes(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    fresh = await _pending_order(database, pid, qty=1, placed_at=now - timedelta(minutes=29))
    stale = await _pending_order(
        database, pid, qty=2, placed_at=now - timedelta(minutes=31), crid="o2"
    )

    closed = await close_expired_orders(database, now=now)
    again = await close_expired_orders(database, now=now)

    assert closed == 1 and again == 0  # 条件更新天然幂等，补跑不重复释放
    assert (await get_order(database, fresh)).payment_status == "PENDING"
    assert (await get_order(database, stale)).payment_status == "CLOSED"
    assert await stock(database, pid) == Stock(on_hand=INITIAL, reserved=1)
    await _no_drift(database)


@pytest.mark.asyncio
async def test_payment_guards_the_deadline_even_without_the_expiry_precheck(
    postgres_app: FastAPI,
) -> None:
    """条件更新本身带截止时间：即使调用方漏了 `expire_if_due`，过期订单也付不了款。"""

    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=INITIAL)
    now = datetime.now(UTC)
    oid = await _pending_order(database, pid, qty=1, placed_at=now - timedelta(minutes=31))

    with pytest.raises(IllegalStateTransitionError):
        async with database.session() as session:
            await pay_order(
                session,
                ctx=CTX,
                order_id=oid,
                client_request_id="p1",
                principal_secret=PRINCIPAL_SECRET,
                audits=_NoAudit(),
                request_id="t",
                now=now,
            )

    assert (await get_order(database, oid)).payment_status == "PENDING"
    assert (await stock(database, pid)).on_hand == INITIAL


@pytest.mark.asyncio
async def test_paying_orders_with_opposite_line_order_does_not_deadlock(
    postgres_app: FastAPI,
) -> None:
    """支付 / 关闭按商品 ID 顺序取行锁：两单以相反顺序含同两件商品，并发支付不互等。"""

    database = database_of(postgres_app)
    pid_a = await seed_product(database, MERCHANT_ONE_ID, on_hand=100)
    pid_b = await seed_product(database, MERCHANT_ONE_ID, on_hand=100)
    now = datetime.now(UTC)
    orders: list[tuple[Any, str]] = []
    for index in range(12):
        ctx = bound_context(MERCHANT_ONE_ID, f"deadlock-{index}")
        assert ctx.buyer_key is not None
        first, second = (pid_a, pid_b) if index % 2 else (pid_b, pid_a)
        await seed_cart(database, MERCHANT_ONE_ID, ctx.buyer_key, {first: 1})
        # 第二行晚一点加入，订单行顺序就与商品 ID 顺序在一半订单里相反。
        await seed_cart(database, MERCHANT_ONE_ID, ctx.buyer_key, {second: 1})
        async with database.session() as session:
            body = await place_order(
                session,
                ctx=ctx,
                coupon_id=None,
                client_request_id=f"o{index}",
                principal_secret=PRINCIPAL_SECRET,
                now=now,
            )
            await session.commit()
        orders.append((ctx, str(body["id"])))

    async def pay(ctx: Any, order_id: str) -> None:
        async with database.session() as session:
            await pay_order(
                session,
                ctx=ctx,
                order_id=order_id,
                client_request_id="p1",
                principal_secret=PRINCIPAL_SECRET,
                audits=_NoAudit(),
                request_id="t",
                now=now,
            )
            await session.commit()

    await asyncio.gather(*[pay(ctx, oid) for ctx, oid in orders])

    assert await stock(database, pid_a) == Stock(on_hand=88, reserved=0)
    assert await stock(database, pid_b) == Stock(on_hand=88, reserved=0)
