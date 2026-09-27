"""顾客端公开目录的只读查询（PRD C1）。

所有查询都以服务端从 `shop_slug` 解析出的 `merchant_id` 为范围；调用方拿不到、也传不进
别的租户标识。
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import Product
from app.models.merchant import Merchant
from app.models.promotion import Coupon
from app.services.v2.coupons import CouponRow

#: 「在售」的唯一定义：已下架、审核中、被驳回的商品对顾客一律不可见。
ON_SALE_STATUS: Final = "ONLINE"


class CatalogReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def shop_names(self, merchant_id: UUID) -> tuple[str, str | None]:
        row = (
            await self._session.execute(
                select(Merchant.display_name, Merchant.display_name_en).where(
                    Merchant.id == merchant_id
                )
            )
        ).one()
        return row.display_name, row.display_name_en

    async def on_sale_products(self, merchant_id: UUID) -> list[Product]:
        """契约 §8.8.2 排序：`created_at DESC, id DESC`。"""

        result = await self._session.execute(
            select(Product)
            .where(Product.merchant_id == merchant_id, Product.status == ON_SALE_STATUS)
            .order_by(Product.created_at.desc(), Product.id.desc())
        )
        return list(result.scalars().all())

    async def merchant_products(self, merchant_id: UUID) -> list[Product]:
        """商家只读内容面包含本店所有状态商品，按创建时间倒序。"""

        result = await self._session.execute(
            select(Product)
            .where(Product.merchant_id == merchant_id)
            .order_by(Product.created_at.desc(), Product.id.desc())
        )
        return list(result.scalars().all())

    async def on_sale_product(self, merchant_id: UUID, product_id: UUID) -> Product | None:
        result = await self._session.execute(
            select(Product).where(
                Product.id == product_id,
                Product.merchant_id == merchant_id,
                Product.status == ON_SALE_STATUS,
            )
        )
        return result.scalar_one_or_none()

    async def coupons(self, merchant_id: UUID) -> list[CouponRow]:
        """本店全部券，按 `created_at DESC, id DESC`；是否生效由 `coupons.is_active` 一处判定。"""

        result = await self._session.execute(
            select(Coupon)
            .where(Coupon.merchant_id == merchant_id)
            .order_by(Coupon.created_at.desc(), Coupon.id.desc())
        )
        return [
            CouponRow(
                id=str(coupon.id),
                name=coupon.name,
                kind=coupon.kind,
                threshold_amount=coupon.threshold_amount,
                discount_amount=coupon.discount_amount,
                discount_rate=coupon.discount_rate,
                product_ids=list(coupon.product_ids),
                starts_at=coupon.starts_at,
                ends_at=coupon.ends_at,
                state=coupon.state,
                created_at=coupon.created_at,
            )
            for coupon in result.scalars().all()
        ]
