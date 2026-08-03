"""可重复执行的演示商家 Seed。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant


@dataclass(frozen=True, slots=True)
class DemoMerchantSeed:
    id: UUID
    merchant_code: str
    display_name: str


@dataclass(frozen=True, slots=True)
class SeedResult:
    created: int
    existing: int


_FIXED_IDS = (
    UUID("00000000-0000-0000-0000-000000000001"),
    UUID("00000000-0000-0000-0000-000000000002"),
    UUID("00000000-0000-0000-0000-000000000003"),
)


def default_merchants(*, merchant_count: int = 3) -> list[DemoMerchantSeed]:
    """生成稳定的虚构商家，便于跨运行复现隔离测试。"""

    if merchant_count < 1:
        raise ValueError("merchant_count 必须大于 0")

    merchants: list[DemoMerchantSeed] = []
    for index in range(merchant_count):
        number = 100 + index
        merchant_code = f"borough-demo-{number}"
        merchant_id = (
            _FIXED_IDS[index] if index < len(_FIXED_IDS) else uuid5(NAMESPACE_URL, merchant_code)
        )
        merchants.append(
            DemoMerchantSeed(
                id=merchant_id,
                merchant_code=merchant_code,
                display_name=f"Borough商家{number}",
            )
        )
    return merchants


async def seed_demo_merchants(
    session: AsyncSession,
    merchants: list[DemoMerchantSeed],
) -> SeedResult:
    """幂等写入演示商家；演示 Token 永不写入数据库。"""

    codes = [merchant.merchant_code for merchant in merchants]
    existing_codes = set(
        await session.scalars(
            select(Merchant.merchant_code).where(Merchant.merchant_code.in_(codes))
        )
    )
    if merchants:
        statement = insert(Merchant).values(
            [
                {
                    "id": merchant.id,
                    "merchant_code": merchant.merchant_code,
                    "display_name": merchant.display_name,
                    "is_demo": True,
                    "status": "ACTIVE",
                }
                for merchant in merchants
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=[Merchant.merchant_code],
            set_={
                "display_name": statement.excluded.display_name,
                "is_demo": True,
                "status": "ACTIVE",
            },
        )
        await session.execute(statement)
        await session.commit()

    return SeedResult(
        created=len(codes) - len(existing_codes),
        existing=len(existing_codes),
    )
