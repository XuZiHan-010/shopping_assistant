"""短批次重建因来源事实删除而陈旧的商家总结；N5 接入 Cron。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.db.session import Database
from app.memory.merchant_store import MerchantMemoryStore
from app.models.memory_v2 import MerchantMemorySummary
from app.models.merchant import Merchant


async def rebuild_once(database: Database, *, now: datetime, limit: int = 20) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("无效的重建批次")
    async with database.session() as session:
        merchant_ids = (await session.scalars(
            select(MerchantMemorySummary.merchant_id)
            .where(MerchantMemorySummary.is_stale.is_(True))
            .distinct()
            .limit(limit)
        )).all()
        rebuilt = 0
        for merchant_id in merchant_ids:
            # 同一商家所有总结在同一事务中重建，防止并发实例交错更新。
            owner = await session.scalar(
                select(Merchant.id).where(Merchant.id == merchant_id)
                .with_for_update(skip_locked=True)
            )
            if owner is None:
                continue
            await MerchantMemoryStore(session).rebuild_summaries(merchant_id=merchant_id, at=now)
            rebuilt += 1
        await session.commit()
        return rebuilt
