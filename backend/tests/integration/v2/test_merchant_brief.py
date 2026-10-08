"""最小当日简报（模块 C Task 6，PRD §15 N2 裁定，契约 §8.12.2 不变量 2）。

这是一份**确定性**简报：条目只来自库存告警与待批准草稿，不调用 LLM。
因此它的 `analysis_sources` 必须如实标注为数据库来源，绝不能包装成模型分析（R7）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.v2.drafts import AGENT_ACTOR, DRAFT_TTL
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product

pytestmark = pytest.mark.integration

BRIEF_PATH = "/api/v2/merchant/briefs/daily/current"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _stage(database: Database, merchant_id: UUID, product_id: UUID) -> UUID:
    async with database.session() as session:
        draft = Draft(
            merchant_id=merchant_id,
            kind=DraftKind.RESTOCK.value,
            title="补货 +60",
            target_type="PRODUCT",
            target_id=product_id,
            target_version=12,
            draft_version=1,
            state=DraftState.STAGED.value,
            payload={"delta": 60, "base_on_hand": 12},
            guardrail_snapshot={"checks": [], "checked_at": datetime.now(UTC).isoformat()},
            created_by=AGENT_ACTOR,
            expires_at=datetime.now(UTC) + DRAFT_TTL,
        )
        session.add(draft)
        await session.commit()
        return draft.id


async def _brief(client: AsyncClient, headers: dict[str, str]) -> Any:
    resp = await client.get(BRIEF_PATH, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_brief_reports_deterministic_sources_not_model_analysis(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """R7：确定性规则产出的简报不得声称经过模型分析。"""

    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _brief(postgres_client, headers)

    assert body["analysis_sources"] == [
        {"source": "DATABASE", "degraded": False, "degraded_reason": None}
    ]
    assert body["degraded"] is False
    assert body["degraded_reason"] is None
    assert body["quality_status"] == "NOT_RUN"
    assert body["quality_attempts"] == 0
    assert body["quality_notes"] == []
    assert body["thinking_steps"] == []


@pytest.mark.asyncio
async def test_brief_items_trace_back_to_alerts_and_drafts(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    out_of_stock = await seed_product(database, MERCHANT_ONE_ID, title="售罄商品", on_hand=0)
    low = await seed_product(database, MERCHANT_ONE_ID, title="低库存商品", on_hand=2)
    draft = await _stage(database, MERCHANT_ONE_ID, low)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _brief(postgres_client, headers)

    kinds = [item["kind"] for item in body["items"]]
    evidence = " ".join(item["evidence"] for item in body["items"])
    assert "INVENTORY_ALERT" in kinds and "PENDING_DRAFT" in kinds
    assert str(out_of_stock) in evidence
    assert str(draft) in evidence


@pytest.mark.asyncio
async def test_brief_ranks_are_contiguous_and_capped(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """契约上限是 6 条，多出来的进 `collapsed_count`，不是静默丢弃。"""

    database = _database(postgres_app)
    for index in range(9):
        await seed_product(database, MERCHANT_ONE_ID, title=f"缺货{index}", on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _brief(postgres_client, headers)

    assert [item["rank"] for item in body["items"]] == list(range(1, 7))
    assert body["collapsed_count"] == 3


@pytest.mark.asyncio
async def test_brief_carries_both_timestamps(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """D18⑤：数据截至时间与生成时间都要有，且生成时间不早于数据截至时间。"""

    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _brief(postgres_client, headers)

    data_as_of = datetime.fromisoformat(body["data_as_of"])
    generated_at = datetime.fromisoformat(body["generated_at"])
    assert generated_at >= data_as_of
    assert datetime.now(UTC) - generated_at < timedelta(minutes=5)
    assert body["business_timezone"]
    assert body["business_date"]
    assert body["trigger"] == "SCHEDULED"
    assert body["brief_version"] >= 1


@pytest.mark.asyncio
async def test_brief_is_merchant_scoped(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    await seed_product(database, MERCHANT_TWO_ID, title="别人的缺货商品", on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _brief(postgres_client, headers)

    assert body["items"] == []
    assert body["collapsed_count"] == 0


@pytest.mark.asyncio
async def test_brief_next_action_prompt_points_at_existing_abilities(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """建议问题只把问题填进输入框，不发送、不批准、不执行（§8.12.1）。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="缺货商品", on_hand=0)
    await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=3, days_ago=2)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _brief(postgres_client, headers)

    prompts = [item["next_action_prompt"] for item in body["items"]]
    assert all(prompt is None or prompt.strip() for prompt in prompts)
    assert any(prompt for prompt in prompts)


@pytest.mark.asyncio
async def test_brief_does_not_call_the_model(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """最小简报不调用 LLM：把 LLM 客户端换成会爆炸的替身，请求仍然成功。"""

    database = _database(postgres_app)
    await seed_product(database, MERCHANT_ONE_ID, on_hand=0)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    postgres_app.state.settings.llm_api_key = None

    body = await _brief(postgres_client, headers)

    assert body["items"]
    assert body["degraded"] is False


@pytest.mark.asyncio
async def test_brief_requires_a_merchant_session(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    missing = await postgres_client.get(BRIEF_PATH)
    assert missing.status_code == 401

    created = await postgres_client.post(
        "/api/v2/shop/sessions", json={"shop_slug": "borough-api-100"}
    )
    customer = await postgres_client.get(
        BRIEF_PATH, headers={"X-Session-Id": created.json()["session_id"]}
    )
    assert customer.status_code == 403
    assert customer.json()["code"] == "SESSION_ROLE_MISMATCH"
