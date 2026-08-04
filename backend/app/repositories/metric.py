"""全商家共享的正式指标定义仓储。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import MetricDefinition


class MetricRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, metric_code: str) -> MetricDefinition | None:
        result = await self._session.execute(
            select(MetricDefinition).where(
                MetricDefinition.metric_code == metric_code,
                MetricDefinition.status != "DEPRECATED",
            )
        )
        return result.scalar_one_or_none()
