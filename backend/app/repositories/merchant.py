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


class MerchantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_demo_by_ids(self, merchant_ids: list[UUID]) -> list[MerchantSummary]:
        if not merchant_ids:
            return []
        result = await self._session.execute(
            select(Merchant.id, Merchant.display_name).where(
                Merchant.id.in_(merchant_ids),
                Merchant.is_demo.is_(True),
                Merchant.status == "ACTIVE",
            )
        )
        return [
            MerchantSummary(merchant_id=merchant_id, display_name=display_name)
            for merchant_id, display_name in result.all()
        ]

    async def get_display_name(self, merchant_id: UUID) -> str | None:
        """管理端按 id 取商家展示名；不筛 is_demo，管理员操作对象可以是任意商家。"""

        return cast(
            str | None,
            await self._session.scalar(
                select(Merchant.display_name).where(Merchant.id == merchant_id)
            ),
        )
