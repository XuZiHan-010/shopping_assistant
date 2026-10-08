"""短批次删除已超过 180 天保存期的顾客记忆；N5 接入 Cron。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select

from app.db.session import Database
from app.memory.customer_store import RETENTION
from app.models.memory_v2 import CustomerMemory


async def purge_once(database: Database, *, now: datetime, limit: int = 500) -> int:
    if not 1 <= limit <= 1000:
        raise ValueError("无效的清理批次")
    async with database.session() as session:
        ids = (await session.scalars(
            select(CustomerMemory.id)
            .where(CustomerMemory.last_confirmed_at <= now - RETENTION)
            .order_by(CustomerMemory.last_confirmed_at, CustomerMemory.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )).all()
        if ids:
            await session.execute(delete(CustomerMemory).where(CustomerMemory.id.in_(ids)))
        await session.commit()
        return len(ids)
