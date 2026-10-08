"""完整每日简报的存储、三源汇总与限流重新生成（N3 阶段 C Task 2，PRD M2、D18）——真实 PostgreSQL。

`GET /current` 现在优先读已存储简报，首次现算后自动落库（不返回 404，见契约 §8.12.3
2026-09-26 修正说明）；`POST /regenerate` 走幂等 + 冷却双重限制。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import Database
from app.models.analytics import Product
from app.models.memory_v2 import CustomerSignal, DailyBrief
from app.services.v2.daily_brief import REGENERATE_COOLDOWN_SECONDS
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration

BRIEF_PATH = "/api/v2/merchant/briefs/daily/current"
REGENERATE_PATH = f"{BRIEF_PATH}/regenerate"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _seed_signal(database: Database, merchant_id: UUID) -> None:
    async with database.session() as session:
        session.add(CustomerSignal(
            merchant_id=merchant_id, kind="CONTENT_GAP", product_id=None,
            product_name="信号测试商品", signal_date=date.today(), count=3,
            derived_from=[{"source_type": "PRODUCT", "source_id": "p1", "content_version": 1}],
            is_ignored=False,
        ))
        await session.commit()


async def _regenerate(
    client: AsyncClient, headers: dict[str, str], *, crid: str = "regen-1"
) -> Any:
    return await client.post(
        REGENERATE_PATH, json={"client_request_id": crid}, headers=headers
    )


@pytest.mark.asyncio
async def test_get_current_brief_persists_first_version(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """首次 GET 现算并自动落库为第 1 版，不是每次都重新计算、永不落盘。"""

    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.get(BRIEF_PATH, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["brief_version"] == 1

    async with database.session() as session:
        rows = (await session.execute(select(DailyBrief))).scalars().all()
    assert len(rows) == 1
    assert rows[0].brief_version == 1


@pytest.mark.asyncio
async def test_get_current_uses_business_date_across_utc_midnight(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 9, 23, 17, tzinfo=UTC)

    monkeypatch.setattr("app.api.routes.v2.merchant_brief.datetime", FixedDateTime)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    first = await postgres_client.get(BRIEF_PATH, headers=headers)
    second = await postgres_client.get(BRIEF_PATH, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["business_date"] == "2026-09-24"
    assert second.json()["brief_version"] == 1


@pytest.mark.asyncio
async def test_get_current_brief_includes_customer_signals(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await _seed_signal(database, MERCHANT_ONE_ID)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.get(BRIEF_PATH, headers=headers)
    assert resp.status_code == 200, resp.text
    kinds = [item["kind"] for item in resp.json()["items"]]
    assert "CUSTOMER_SIGNAL" in kinds


@pytest.mark.asyncio
async def test_regenerate_replaces_version_not_row(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    await postgres_client.get(BRIEF_PATH, headers=headers)  # 先落第 1 版

    resp = await _regenerate(postgres_client, headers, crid="regen-a")
    assert resp.status_code == 200, resp.text
    assert resp.json()["brief_version"] == 2
    assert resp.json()["trigger"] == "REGENERATED"

    async with database.session() as session:
        rows = (await session.execute(select(DailyBrief))).scalars().all()
    assert len(rows) == 1
    assert rows[0].brief_version == 2


@pytest.mark.asyncio
async def test_regenerate_within_cooldown_is_rate_limited(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    await postgres_client.get(BRIEF_PATH, headers=headers)

    first = await _regenerate(postgres_client, headers, crid="regen-b1")
    assert first.status_code == 200, first.text

    second = await _regenerate(postgres_client, headers, crid="regen-b2")
    assert second.status_code == 429, second.text
    assert second.json()["code"] == "RATE_LIMITED"

    async with database.session() as session:
        rows = (await session.execute(select(DailyBrief))).scalars().all()
    assert rows[0].brief_version == 2  # 被拒绝的那次没有产生新版本


@pytest.mark.asyncio
async def test_concurrent_regenerates_only_one_passes_cooldown(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.routes.v2 import merchant_brief

    original = merchant_brief._current_facts

    async def delayed_facts(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(0.1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(merchant_brief, "_current_facts", delayed_facts)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    await postgres_client.get(BRIEF_PATH, headers=headers)
    responses = await asyncio.gather(*(
        _regenerate(postgres_client, headers, crid=f"regen-concurrent-{index}")
        for index in range(5)
    ))
    assert [response.status_code for response in responses].count(200) == 1
    assert [response.status_code for response in responses].count(429) == 4
    async with _database(postgres_app).session() as session:
        row = (await session.execute(select(DailyBrief))).scalar_one()
        assert row.brief_version == 2


@pytest.mark.asyncio
async def test_regenerate_replay_of_same_client_request_id_does_not_double_apply(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """同一 `client_request_id` 重放直接回放首次结果，不重复递增版本号（§8.7.3）。"""

    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    await postgres_client.get(BRIEF_PATH, headers=headers)

    first = await _regenerate(postgres_client, headers, crid="regen-same")
    second = await _regenerate(postgres_client, headers, crid="regen-same")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()

    async with database.session() as session:
        rows = (await session.execute(select(DailyBrief))).scalars().all()
    assert rows[0].brief_version == 2


@pytest.mark.asyncio
async def test_regenerate_requires_a_merchant_session(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    resp = await postgres_client.post(REGENERATE_PATH, json={"client_request_id": "regen-c"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_regenerate_after_cooldown_expires_succeeds(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """冷却窗口过后，同一商家可以再次成功重新生成——不是永久锁死。"""

    del monkeypatch
    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    await postgres_client.get(BRIEF_PATH, headers=headers)
    await _regenerate(postgres_client, headers, crid="regen-d1")

    # 直接把上一版本的 generated_at 往前拨，模拟冷却窗口已经过去，
    # 不真的等待 REGENERATE_COOLDOWN_SECONDS 秒（避免拖慢测试）。
    async with database.session() as session:
        row = (await session.execute(select(DailyBrief))).scalars().one()
        row.generated_at = datetime.now(UTC) - timedelta(seconds=REGENERATE_COOLDOWN_SECONDS + 1)
        await session.commit()

    resp = await _regenerate(postgres_client, headers, crid="regen-d2")
    assert resp.status_code == 200, resp.text
    assert resp.json()["brief_version"] == 3


@pytest.mark.asyncio
async def test_regenerate_never_uses_stale_payload_as_a_fact_source(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """D18①：昨天/上一版本的简报正文本身不进数字来源——重新生成必须反映当前真实事实，
    不能把旧 `payload` 里的条目原样带过来（哪怕旧数据现在已经不成立）。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="缺货商品", on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    await postgres_client.get(BRIEF_PATH, headers=headers)  # 落第 1 版：含缺货告警

    # 商品重新上架、库存充足——旧简报里的"缺货"事实现在已经不成立。
    async with database.session() as session:
        row = await session.get(Product, product)
        assert row is not None
        row.stock_on_hand = 999
        await session.commit()

    resp = await _regenerate(postgres_client, headers, crid="regen-fact-source")
    assert resp.status_code == 200, resp.text
    out_of_stock_items = [
        item for item in resp.json()["items"]
        if item["kind"] == "INVENTORY_ALERT" and "已售罄" in item["title"]
    ]
    assert not out_of_stock_items  # 已经不缺货，不该再作为「已售罄」告警出现
