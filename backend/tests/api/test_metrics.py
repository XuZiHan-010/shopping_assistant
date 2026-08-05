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
        # 单独补一条已废弃指标：口径端点必须能把治理状态原样暴露出来，
        # 不能像聊天链路那样把 DEPRECATED 过滤成「查无此指标」。
        session.add(
            MetricDefinition(
                metric_code="legacy_gmv_1d",
                display_name="历史 GMV（已废弃）",
                unit="元",
                business_definition="历史口径，已被 gmv 取代。",
                sql_definition="SUM(legacy_gmv)",
                source="Borough 指标目录",
                owner="经营分析组",
                status="DEPRECATED",
            )
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
async def test_deprecated_metric_still_returns_its_definition(seeded_client: AsyncClient) -> None:
    """废弃指标要能被口径面板看到并标成 DEPRECATED，而不是和拼错的指标码一样 404。"""

    response = await seeded_client.get("/api/metrics/legacy_gmv_1d", headers=MERCHANT_ONE_AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["metric_code"] == "legacy_gmv_1d"
    assert payload["status"] == "DEPRECATED"


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
