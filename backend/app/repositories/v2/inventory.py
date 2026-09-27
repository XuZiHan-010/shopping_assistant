"""库存事实的只读查询（M5）。

近 30 天销量**由订单明细当场计算**，不另存计数器：多一个计数器就多一处可能与订单
事实不一致的地方，而告警要在商家眼里等同于"照着订单算出来的"。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import Order, OrderItem, Product
from app.services.v2.inventory_alerts import SALES_WINDOW_DAYS, InventoryFacts

#: 只有已付款订单算销量；未付款与已关闭订单不构成需求信号。
PAID_STATUS = "PAID"
#: 只对在售商品告警：已下架商品不需要补货提醒。
LISTED_STATUS = "ONLINE"


class InventoryReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def facts_for_merchant(self, merchant_id: UUID, *, now: datetime) -> list[InventoryFacts]:
        rows = await self._session.execute(self._statement(merchant_id, now=now))
        return [
            InventoryFacts(
                product_id=str(row.id),
                product_name=row.title,
                stock_on_hand=row.stock_on_hand,
                stock_reserved=row.stock_reserved,
                low_stock_threshold=row.low_stock_threshold,
                sold_last_30d=int(row.sold_last_30d or 0),
                listed_at=row.listed_at,
            )
            for row in rows
        ]

    @staticmethod
    def _statement(merchant_id: UUID, *, now: datetime) -> Select[tuple[object, ...]]:
        since = now - timedelta(days=SALES_WINDOW_DAYS)
        sold = func.coalesce(
            func.sum(case((Order.id.is_not(None), OrderItem.quantity), else_=0)), 0
        )
        return (
            select(
                Product.id,
                Product.title,
                Product.stock_on_hand,
                Product.stock_reserved,
                Product.low_stock_threshold,
                Product.listed_at,
                sold.label("sold_last_30d"),
            )
            .select_from(Product)
            .outerjoin(
                OrderItem,
                (OrderItem.product_id == Product.id)
                & (OrderItem.merchant_id == Product.merchant_id),
            )
            .outerjoin(
                Order,
                (Order.id == OrderItem.order_id)
                & (Order.merchant_id == Product.merchant_id)
                & (Order.payment_status == PAID_STATUS)
                & (Order.paid_at >= since),
            )
            .where(Product.merchant_id == merchant_id, Product.status == LISTED_STATUS)
            .group_by(Product.id)
        )
