"""`GET /api/v2/merchant/drafts` 的 `batch_id` 查询过滤（N3 阶段 C Task 3 步骤 0，契约 §8.13.3）。

`batch_id` 只应用于按批次分组查看商品内容批量草稿；本文件直接播种草稿行验证过滤本身，
不依赖 Task 3 步骤 1-2 的商品内容起草工具是否已实现。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.db.session import Database
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.v2.drafts import AGENT_ACTOR, DRAFT_TTL
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers

pytestmark = pytest.mark.integration

DRAFTS_PATH = "/api/v2/merchant/drafts"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _stage_content_change(
    database: Database, merchant_id: UUID, *, batch_id: UUID | None, product_id: UUID | None = None
) -> UUID:
    async with database.session() as session:
        draft = Draft(
            merchant_id=merchant_id,
            kind=DraftKind.CONTENT_CHANGE.value,
            title="商品内容更新",
            target_type="PRODUCT",
            target_id=product_id or uuid4(),
            target_version=1,
            draft_version=1,
            state=DraftState.STAGED.value,
            payload={"attributes": {}},
            guardrail_snapshot={"checks": [], "checked_at": datetime.now(UTC).isoformat()},
            created_by=AGENT_ACTOR,
            expires_at=datetime.now(UTC) + DRAFT_TTL,
            batch_id=batch_id,
        )
        session.add(draft)
        await session.commit()
        return draft.id


@pytest.mark.asyncio
async def test_list_drafts_filters_by_batch_id(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    batch = uuid4()
    other_batch = uuid4()
    in_batch = {
        await _stage_content_change(database, MERCHANT_ONE_ID, batch_id=batch),
        await _stage_content_change(database, MERCHANT_ONE_ID, batch_id=batch),
    }
    await _stage_content_change(database, MERCHANT_ONE_ID, batch_id=other_batch)
    await _stage_content_change(database, MERCHANT_ONE_ID, batch_id=None)

    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.get(
        DRAFTS_PATH, params={"batch_id": str(batch)}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert ids == {str(item) for item in in_batch}


@pytest.mark.asyncio
async def test_list_drafts_with_malformed_batch_id_returns_empty_not_all_unbatched(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """格式不对的 batch_id 必须返回空列表，不能意外匹配所有 batch_id 为 NULL 的草稿。"""

    database = _database(postgres_app)
    await _stage_content_change(database, MERCHANT_ONE_ID, batch_id=None)

    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.get(
        DRAFTS_PATH, params={"batch_id": "not-a-uuid"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []


@pytest.mark.asyncio
async def test_list_drafts_without_batch_id_returns_all_kinds(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """不传 batch_id 时行为不变：仍按 state/kind 过滤，不因为新增字段而漏掉旧调用方式。"""

    database = _database(postgres_app)
    solo = await _stage_content_change(database, MERCHANT_ONE_ID, batch_id=None)

    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.get(
        DRAFTS_PATH, params={"kind": "CONTENT_CHANGE"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert str(solo) in ids
