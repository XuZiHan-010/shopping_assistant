"""交易闭环（交易计划 Task 3–7）测试的共用播种与读取助手。

结账、支付、订单读取三组测试都要同一组事实：已绑定顾客会话、购物车行、库存三元组、订单与事件行。
集中在这里，免得「占用量」「事件条数」这类判定在各测试文件之间悄悄漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.models.analytics import Order, Product
from app.models.cart import CartLine
from app.models.events import FulfillmentEvent, InventoryEvent

SHOP = "borough-api-100"
OTHER_SHOP = "borough-api-101"
PRINCIPAL_SECRET = b"trade-tests-principal-secret-0123456789"


@dataclass(frozen=True)
class Stock:
    on_hand: int
    reserved: int

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


def database_of(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


def bound_context(merchant_id: UUID, buyer_key: str, *, shop_slug: str = SHOP) -> SessionContext:
    """直接构造已绑定顾客主体；服务层用例不必先走一遍 HTTP 绑定。"""

    return SessionContext(
        session_record_id=uuid4(),
        role=SessionRole.CUSTOMER,
        merchant_id=merchant_id,
        buyer_key=buyer_key,
        shop_slug=shop_slug,
    )


async def bound_customer(
    client: AsyncClient, app: FastAPI, *, buyer_key: str, shop_slug: str = SHOP
) -> dict[str, str]:
    """经真实路由签发访客会话并绑定到 `buyer_key`，返回请求头。"""

    app.state.settings.demo_deployment_mode = True
    app.state.settings.demo_customer_identities = {shop_slug: buyer_key}
    created = await client.post("/api/v2/shop/sessions", json={"shop_slug": shop_slug})
    assert created.status_code == 201, created.text
    headers = {"X-Session-Id": created.json()["session_id"]}
    bound = await client.post("/api/v2/shop/sessions/demo-customer", json={}, headers=headers)
    assert bound.status_code == 200, bound.text
    return headers


async def put_cart(
    client: AsyncClient, headers: dict[str, str], product_id: UUID, quantity: int
) -> None:
    resp = await client.put(
        f"/api/v2/shop/cart/items/{product_id}", json={"quantity": quantity}, headers=headers
    )
    assert resp.status_code == 200, resp.text


async def seed_cart(
    database: Database, merchant_id: UUID, buyer_key: str, lines: dict[UUID, int]
) -> None:
    async with database.session() as session:
        for product_id, quantity in lines.items():
            session.add(
                CartLine(
                    merchant_id=merchant_id,
                    buyer_key=buyer_key,
                    product_id=product_id,
                    quantity=quantity,
                )
            )
        await session.commit()


async def stock(database: Database, product_id: UUID) -> Stock:
    async with database.session() as session:
        row = (
            await session.execute(
                select(Product.stock_on_hand, Product.stock_reserved).where(
                    Product.id == product_id
                )
            )
        ).one()
    return Stock(on_hand=row.stock_on_hand, reserved=row.stock_reserved)


async def set_product(database: Database, product_id: UUID, **values: Any) -> None:
    async with database.session() as session:
        await session.execute(update(Product).where(Product.id == product_id).values(**values))
        await session.commit()


async def set_order(database: Database, order_id: UUID | str, **values: Any) -> None:
    async with database.session() as session:
        await session.execute(update(Order).where(Order.id == UUID(str(order_id))).values(**values))
        await session.commit()


async def get_order(database: Database, order_id: UUID | str) -> Order:
    async with database.session() as session:
        order = await session.get(Order, UUID(str(order_id)))
        assert order is not None
        return order


async def count_orders(database: Database) -> int:
    async with database.session() as session:
        return int(await session.scalar(select(func.count()).select_from(Order)) or 0)


async def fulfillment_events(database: Database, order_id: UUID | str) -> list[str]:
    async with database.session() as session:
        rows = await session.scalars(
            select(FulfillmentEvent.event_type)
            .where(FulfillmentEvent.subject_id == UUID(str(order_id)))
            .order_by(FulfillmentEvent.occurred_at, FulfillmentEvent.created_at)
        )
        return list(rows.all())


async def inventory_events(database: Database, product_id: UUID) -> list[tuple[str, int]]:
    async with database.session() as session:
        rows = await session.execute(
            select(InventoryEvent.event_type, InventoryEvent.payload)
            .where(InventoryEvent.subject_id == product_id)
            .order_by(InventoryEvent.occurred_at, InventoryEvent.created_at)
        )
        return [(event_type, int(payload["quantity"])) for event_type, payload in rows.all()]


def minutes_ago(now: datetime, minutes: int) -> datetime:
    return now - timedelta(minutes=minutes)
