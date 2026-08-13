"""指标定义仓储集成测试。

`MetricRepository` 对同一份数据故意提供两种视角（见 `app/repositories/metric.py`
的 docstring）：`get_by_code` 给聊天链路用，过滤掉 DEPRECATED；
`get_by_code_including_deprecated` 给指标口径查询端点用，原样返回治理元数据。
这里直接对着真实 PostgreSQL 验证两者的差异，避免以后有人「顺手」把它们合并成
一个方法，导致聊天链路又能拿废弃口径回答问题，或者口径端点又把废弃指标误判为
「不存在」。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import MetricDefinition
from app.repositories.metric import MetricRepository


async def _seed_deprecated_metric(session: AsyncSession) -> None:
    session.add(
        MetricDefinition(
            metric_code="legacy_gmv_1d",
            display_name="历史 GMV（已废弃）",
            unit="元",
            business_definition="历史口径，已被 gmv 取代。",
            sql_definition="SUM(legacy_gmv)",
            source="METRIC_CATALOG",
            owner="经营分析组",
            status="DEPRECATED",
            dimensions=["date"],
            source_database="public",
            source_table="orders",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_get_by_code_hides_deprecated_metrics(db_session: AsyncSession) -> None:
    """聊天链路（`MetricCatalog.resolve` 经 `get_chat_service` 注入的正是这个方法）
    不该拿废弃口径去回答商家的问题。"""

    await _seed_deprecated_metric(db_session)

    result = await MetricRepository(db_session).get_by_code("legacy_gmv_1d")

    assert result is None


@pytest.mark.asyncio
async def test_get_by_code_including_deprecated_exposes_governance_status(
    db_session: AsyncSession,
) -> None:
    """指标口径查询端点需要把废弃状态原样暴露出来，而不是把它当成指标码不存在。"""

    await _seed_deprecated_metric(db_session)

    result = await MetricRepository(db_session).get_by_code_including_deprecated("legacy_gmv_1d")

    assert result is not None
    assert result.status == "DEPRECATED"


@pytest.mark.asyncio
async def test_get_by_code_including_deprecated_still_returns_none_for_unknown_codes(
    db_session: AsyncSession,
) -> None:
    """真正不存在的指标码必须仍然是 404，不能因为不过滤状态就变成「什么都能命中」。"""

    result = await MetricRepository(db_session).get_by_code_including_deprecated(
        "not_a_real_metric"
    )

    assert result is None
