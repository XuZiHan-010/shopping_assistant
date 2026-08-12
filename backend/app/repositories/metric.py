"""全商家共享的正式指标定义仓储。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import MetricDefinition


class MetricRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_code(self, metric_code: str) -> MetricDefinition | None:
        """供聊天链路（`MetricCatalog.resolve`）使用：解答问题时排除已废弃口径。

        聊天回答不应该拿废弃指标的算法去回答商家的问题，所以这里过滤掉
        `status == "DEPRECATED"` 的行——查不到时上层会退化到 LLM 生成候选口径。
        指标口径查询端点（`GET /api/metrics/{code}`）不能用这个方法：它的职责
        是把治理元数据（含废弃状态）原样暴露给前端，用这个方法会让废弃指标
        永远 404，跟拼错的指标码分不清。见 `get_by_code_including_deprecated`。
        """

        result = await self._session.execute(
            select(MetricDefinition).where(
                MetricDefinition.metric_code == metric_code,
                MetricDefinition.status != "DEPRECATED",
            )
        )
        return result.scalar_one_or_none()

    async def get_by_code_including_deprecated(self, metric_code: str) -> MetricDefinition | None:
        """供指标口径查询端点使用：不过滤状态，原样返回治理元数据。

        `GET /api/metrics/{code}` 的产品目的就是把口径状态（含 DEPRECATED）
        显示给商家，因此这里不能复用 `get_by_code` 的过滤逻辑——否则废弃指标
        会被误判为「指标码不存在」。真正不存在的指标码仍然返回 None。
        """

        result = await self._session.execute(
            select(MetricDefinition).where(MetricDefinition.metric_code == metric_code)
        )
        return result.scalar_one_or_none()
