"""指标口径端点。PRD 要求口径面板展示来源、负责人和状态三项，缺一前端只能留白。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.metrics.seed import METRIC_SEED
from app.models.knowledge import MetricDefinition
from tests.conftest import MERCHANT_ONE_AUTH


@pytest.fixture
async def seeded_client(
    postgres_client: AsyncClient,
    postgres_app: FastAPI,
) -> AsyncIterator[AsyncClient]:
    """指标目录不按商家隔离，但 `postgres_app` 的 TRUNCATE 会连带清空它。

    迁移里的 Seed 只在库刚建好、还没被这个夹具截断时存在，所以这里按
    `METRIC_SEED`（应用侧的口径来源）重新插入一份，供本模块的用例使用。
    """

    async with postgres_app.state.database.session() as session:
        session.add_all(
            MetricDefinition(
                metric_code=item.metric_code,
                display_name=item.display_name,
                unit=item.unit,
                business_definition=item.business_definition,
                sql_definition=item.sql_definition,
                source=item.source,
                owner=item.owner,
            )
            for item in METRIC_SEED
        )
        await session.commit()
    yield postgres_client


@pytest.mark.asyncio
async def test_known_metric_returns_the_full_definition(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/metrics/gmv", headers=MERCHANT_ONE_AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["metric_code"] == "gmv"
    assert payload["display_name"] == "成交 GMV"
    assert payload["unit"] == "元"
    assert payload["source"]
    assert payload["owner"]
    assert payload["status"] in {"ACTIVE", "DEPRECATED", "UNVERIFIED"}


@pytest.mark.asyncio
async def test_unknown_metric_returns_404_error_contract(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/metrics/not_a_metric", headers=MERCHANT_ONE_AUTH)

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_missing_token_is_rejected(seeded_client: AsyncClient) -> None:
    response = await seeded_client.get("/api/metrics/gmv")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"
