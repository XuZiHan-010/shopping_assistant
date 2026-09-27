"""结账事务的并发与幂等（交易计划 Task 3，PRD §7.4 不变量 1/2，契约 §8.10.4）——真实 PostgreSQL。

这些用例在 Fake 仓储上跑绿毫无意义：它们测的正是数据库的行锁与条件更新。
每个并发参与者用各自的数据库会话与已绑定顾客主体，直接调用结账服务。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from app.core.errors import (
    AppError,
    InsufficientStockError,
    RequestInProgressError,
)
from app.core.session import SessionContext
from app.db.session import Database
from app.jobs.rebuild_projections import rebuild_projections
from app.models.cart import CartLine
from app.services.v2.checkout import place_order
from tests.conftest import MERCHANT_ONE_ID
from tests.support.merchant_v2 import seed_product
from tests.support.trade import (
    PRINCIPAL_SECRET,
    Stock,
    bound_context,
    count_orders,
    database_of,
    fulfillment_events,
    inventory_events,
    seed_cart,
    stock,
)

pytestmark = pytest.mark.integration


async def _submit(
    database: Database, ctx: SessionContext, *, crid: str = "r1", coupon_id: str | None = None
) -> dict[str, Any] | AppError:
    try:
        async with database.session() as session:
            body = await place_order(
                session,
                ctx=ctx,
                coupon_id=coupon_id,
                client_request_id=crid,
                principal_secret=PRINCIPAL_SECRET,
                now=datetime.now(UTC),
            )
            await session.commit()
            return body
    except AppError as error:
        return error


def _created(result: object) -> bool:
    return isinstance(result, dict) and "id" in result


@pytest.mark.asyncio
async def test_last_unit_race_has_exactly_one_winner(postgres_app: FastAPI) -> None:
    """PRD §7.4 不变量 1：任何路径都不得产生负可售量。"""

    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=1)
    buyers = [bound_context(MERCHANT_ONE_ID, f"race-buyer-{i}") for i in range(10)]
    for ctx in buyers:
        assert ctx.buyer_key is not None
        await seed_cart(database, MERCHANT_ONE_ID, ctx.buyer_key, {pid: 1})

    results = await asyncio.gather(*[_submit(database, ctx) for ctx in buyers])

    assert sum(1 for r in results if _created(r)) == 1
    losers = [r for r in results if not _created(r)]
    assert all(isinstance(r, InsufficientStockError) for r in losers)
    assert (await stock(database, pid)).available == 0
    assert (await stock(database, pid)).reserved == 1
    assert await count_orders(database) == 1


@pytest.mark.asyncio
async def test_many_buyers_never_oversell(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=5)
    buyers = [bound_context(MERCHANT_ONE_ID, f"crowd-{i}") for i in range(12)]
    for ctx in buyers:
        assert ctx.buyer_key is not None
        await seed_cart(database, MERCHANT_ONE_ID, ctx.buyer_key, {pid: 1})

    results = await asyncio.gather(*[_submit(database, ctx) for ctx in buyers])

    assert sum(1 for r in results if _created(r)) == 5
    assert await stock(database, pid) == Stock(on_hand=5, reserved=5)


@pytest.mark.asyncio
async def test_opposite_line_order_does_not_deadlock(postgres_app: FastAPI) -> None:
    """两单以相反顺序加购同两件商品：锁按商品 ID 排序获取，不会互等。"""

    database = database_of(postgres_app)
    pid_a = await seed_product(database, MERCHANT_ONE_ID, on_hand=50)
    pid_b = await seed_product(database, MERCHANT_ONE_ID, on_hand=50)
    buyers = [bound_context(MERCHANT_ONE_ID, f"cross-{i}") for i in range(8)]
    for index, ctx in enumerate(buyers):
        assert ctx.buyer_key is not None
        lines = {pid_a: 1, pid_b: 1} if index % 2 else {pid_b: 1, pid_a: 1}
        await seed_cart(database, MERCHANT_ONE_ID, ctx.buyer_key, lines)

    results = await asyncio.wait_for(
        asyncio.gather(*[_submit(database, ctx) for ctx in buyers]), timeout=30
    )

    assert all(_created(r) for r in results), results
    assert (await stock(database, pid_a)).reserved == 8


@pytest.mark.asyncio
async def test_failed_line_rolls_back_whole_order(postgres_app: FastAPI) -> None:
    """任一行不可用，整单回滚——不得出现「部分占库」；不可用项逐条列出，只给档位。"""

    database = database_of(postgres_app)
    pid_a = await seed_product(database, MERCHANT_ONE_ID, on_hand=5)
    pid_b = await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    ctx = bound_context(MERCHANT_ONE_ID, "partial-buyer")
    assert ctx.buyer_key is not None
    await seed_cart(database, MERCHANT_ONE_ID, ctx.buyer_key, {pid_a: 1, pid_b: 1})

    result = await _submit(database, ctx)

    assert isinstance(result, InsufficientStockError)
    assert result.details == [
        {"product_id": str(pid_b), "reason": "OUT_OF_STOCK", "stock_band": "OUT_OF_STOCK"}
    ]
    assert (await stock(database, pid_a)).reserved == 0
    assert await count_orders(database) == 0
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(CartLine)) == 2


@pytest.mark.asyncio
async def test_duplicate_submission_returns_same_order(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=5)
    ctx = bound_context(MERCHANT_ONE_ID, "dup-buyer")
    assert ctx.buyer_key is not None
    await seed_cart(database, MERCHANT_ONE_ID, ctx.buyer_key, {pid: 1})

    first = await _submit(database, ctx, crid="r1")
    second = await _submit(database, ctx, crid="r1")

    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["id"] == second["id"]
    assert (await stock(database, pid)).reserved == 1  # 只占一次
    assert await count_orders(database) == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_submission_creates_one_order(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=5)
    ctx = bound_context(MERCHANT_ONE_ID, "dup-race-buyer")
    assert ctx.buyer_key is not None
    await seed_cart(database, MERCHANT_ONE_ID, ctx.buyer_key, {pid: 1})

    results = await asyncio.gather(*[_submit(database, ctx, crid="same") for _ in range(4)])

    ids = {r["id"] for r in results if isinstance(r, dict)}
    assert len(ids) == 1
    assert all(isinstance(r, dict | RequestInProgressError) for r in results), results
    assert (await stock(database, pid)).reserved == 1


@pytest.mark.asyncio
async def test_same_request_id_from_another_customer_is_independent(
    postgres_app: FastAPI,
) -> None:
    """§8.7.3：幂等唯一域含主体摘要，同店另一顾客碰巧用同一 ID 不受影响。"""

    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=5)
    alice = bound_context(MERCHANT_ONE_ID, "alice")
    bob = bound_context(MERCHANT_ONE_ID, "bob")
    await seed_cart(database, MERCHANT_ONE_ID, "alice", {pid: 1})
    await seed_cart(database, MERCHANT_ONE_ID, "bob", {pid: 2})

    first = await _submit(database, alice, crid="shared-id")
    second = await _submit(database, bob, crid="shared-id")

    assert isinstance(first, dict) and isinstance(second, dict)
    assert first["id"] != second["id"]
    assert second["item_count"] == 2
    assert (await stock(database, pid)).reserved == 3


@pytest.mark.asyncio
async def test_order_writes_events_that_rebuild_the_projection(postgres_app: FastAPI) -> None:
    """§8.10.4：同一事务写 ORDER_PLACED 与订单占用库存事件；投影可由事件重算且无漂移。"""

    database = database_of(postgres_app)
    pid = await seed_product(database, MERCHANT_ONE_ID, on_hand=5)
    ctx = bound_context(MERCHANT_ONE_ID, "ledger-buyer")
    await seed_cart(database, MERCHANT_ONE_ID, "ledger-buyer", {pid: 2})

    body = await _submit(database, ctx)

    assert isinstance(body, dict)
    assert await fulfillment_events(database, body["id"]) == ["ORDER_PLACED"]
    assert await inventory_events(database, pid) == [("ORDER_RESERVE", 2)]
    async with database.session() as session:
        report = await rebuild_projections(session, merchant_id=MERCHANT_ONE_ID)
    assert report.mismatches == 0, report.drift
    async with database.session() as session:
        remaining = await session.scalar(
            select(func.count()).select_from(CartLine).where(CartLine.buyer_key == "ledger-buyer")
        )
    assert remaining == 0  # 下单成功后清空已下单的购物车
