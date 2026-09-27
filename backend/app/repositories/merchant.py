"""商家数据访问。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant


@dataclass(frozen=True, slots=True)
class MerchantSummary:
    merchant_id: UUID
    display_name: str
    #: 人工维护的英文展示名；缺失时调用方回退到 `display_name` 本身，
    #: 不猜测或调用模型生成（见 `app.models.merchant.Merchant.display_name_en`）。
    display_name_en: str | None = None


class MerchantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_demo_by_ids(self, merchant_ids: list[UUID]) -> list[MerchantSummary]:
        if not merchant_ids:
            return []
        result = await self._session.execute(
            select(Merchant.id, Merchant.display_name, Merchant.display_name_en).where(
                Merchant.id.in_(merchant_ids),
                Merchant.is_demo.is_(True),
                Merchant.status == "ACTIVE",
            )
        )
        return [
            MerchantSummary(
                merchant_id=merchant_id,
                display_name=display_name,
                display_name_en=display_name_en,
            )
            for merchant_id, display_name, display_name_en in result.all()
        ]

    async def get_active_by_shop_slug(self, shop_slug: str) -> UUID | None:
        """公开 `shop_slug` 到可信 `merchant_id` 的唯一映射入口（PRD §9 SEC3）。

        当前没有独立的店铺表，`merchant_code` 本身就是稳定、唯一、
        小写连字符格式的商家标识，两者复用同一列，不新建冗余字段。
        """

        return cast(
            UUID | None,
            await self._session.scalar(
                select(Merchant.id).where(
                    Merchant.merchant_code == shop_slug, Merchant.status == "ACTIVE"
                )
            ),
        )

    async def get_display_name(self, merchant_id: UUID) -> str | None:
        """管理端按 id 取商家展示名；不筛 is_demo，管理员操作对象可以是任意商家。"""

        return cast(
            str | None,
            await self._session.scalar(
                select(Merchant.display_name).where(Merchant.id == merchant_id)
            ),
        )
