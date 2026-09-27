"""商家 v2 端点测试的共用播种与会话助手（模块 C）。

集中在这里是因为 Task 1–8 都要同一组事实：一个有库存三元组的商品、若干已付款订单、
一个商家会话。各测试文件各写一份会让「销量口径」这类判定在测试之间悄悄漂移。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from httpx import AsyncClient

from app.db.session import Database
from app.models.analytics import Order, OrderItem, Product

UNIT_PRICE = Decimal("100.00")


async def merchant_session_headers(client: AsyncClient, auth: dict[str, str]) -> dict[str, str]:
    resp = await client.post("/api/v2/merchant/sessions", json={}, headers=auth)
    assert resp.status_code == 201, resp.text
    return {"X-Session-Id": resp.json()["session_id"]}


async def seed_product(
    database: Database,
    merchant_id: UUID,
    *,
    title: str = "测试商品",
    on_hand: int = 40,
    reserved: int = 0,
    low_stock_threshold: int | None = 5,
    listed_days_ago: int = 400,
    status: str = "ONLINE",
    now: datetime | None = None,
) -> UUID:
    moment = now or datetime.now(UTC)
    listed_at = moment - timedelta(days=listed_days_ago)
    async with database.session() as session:
        product = Product(
            merchant_id=merchant_id,
            business_date=listed_at.date(),
            product_code=f"sku-{uuid4().hex[:12]}",
            title=title,
            category="测试类目",
            price=UNIT_PRICE,
            status=status,
            listed_at=listed_at,
            stock_on_hand=on_hand,
            stock_reserved=reserved,
            low_stock_threshold=low_stock_threshold,
        )
        session.add(product)
        await session.commit()
        return product.id


async def seed_paid_order(
    database: Database,
    merchant_id: UUID,
    product_id: UUID,
    *,
    quantity: int,
    days_ago: int = 1,
    now: datetime | None = None,
) -> UUID:
    """一笔已付款订单；库存告警的销量口径只认已付款订单。"""

    moment = (now or datetime.now(UTC)) - timedelta(days=days_ago)
    line_total = UNIT_PRICE * quantity
    async with database.session() as session:
        order = Order(
            merchant_id=merchant_id,
            business_date=moment.date(),
            order_no=f"ord-{uuid4().hex[:12]}",
            buyer_key="demo-buyer-1",
            order_status="PAID",
            total_amount=line_total,
            paid_amount=line_total,
            placed_at=moment,
            paid_at=moment,
            payment_status="PAID",
            fulfillment_status="NOT_SHIPPED",
            lifecycle_origin="V2",
        )
        session.add(order)
        await session.flush()
        session.add(
            OrderItem(
                merchant_id=merchant_id,
                business_date=moment.date(),
                order_id=order.id,
                product_id=product_id,
                quantity=quantity,
                item_amount=line_total,
                unit_price=UNIT_PRICE,
                discount_amount=Decimal("0.00"),
                line_total=line_total,
            )
        )
        await session.commit()
        return order.id
