"""商家数据访问。"""

from __future__ import annotations

from dataclasses import dataclass
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
