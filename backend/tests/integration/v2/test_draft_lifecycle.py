"""草稿列表、丢弃与过期（模块 C Task 5，契约 §8.13.2、§8.13.3）。

三个终态（`APPLIED` / `DISCARDED` / `EXPIRED`）都不可再迁出，这是 PRD §7.3 不变量 1；
过期任务只做批量收尾，业务路径自己就能判定过期。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update

from app.db.session import Database
from app.jobs.expire_drafts import expire_drafts
from app.models.drafts import Draft
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.v2.drafts import AGENT_ACTOR, DRAFT_TTL
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration

DRAFTS_PATH = "/api/v2/merchant/drafts"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _stage(
    database: Database,
    merchant_id: UUID,
    product_id: UUID,
    *,
    delta: int = 60,
    state: DraftState = DraftState.STAGED,
    created_days_ago: int = 0,
) -> UUID:
    created = datetime.now(UTC) - timedelta(days=created_days_ago)
    async with database.session() as session:
        draft = Draft(
            merchant_id=merchant_id,
            kind=DraftKind.RESTOCK.value,
            title=f"补货 +{delta}",
            target_type="PRODUCT",
            target_id=product_id,
            target_version=12,
            draft_version=1,
            state=state.value,
            payload={"delta": delta, "base_on_hand": 12},
            guardrail_snapshot={"checks": [], "checked_at": created.isoformat()},
            created_by=AGENT_ACTOR,
            expires_at=created + DRAFT_TTL,
        )
        session.add(draft)
        await session.commit()
        draft_id = draft.id
    if created_days_ago:
        async with database.session() as session:
            await session.execute(
                update(Draft).where(Draft.id == draft_id).values(created_at=created)
            )
            await session.commit()
    return draft_id


async def _list(client: AsyncClient, headers: dict[str, str], **params: Any) -> Any:
    resp = await client.get(DRAFTS_PATH, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_list_only_returns_own_staged_drafts(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    mine_product = await seed_product(database, MERCHANT_ONE_ID)
    theirs_product = await seed_product(database, MERCHANT_TWO_ID)
    mine = await _stage(database, MERCHANT_ONE_ID, mine_product)
    applied = await _stage(database, MERCHANT_ONE_ID, mine_product, state=DraftState.APPLIED)
    theirs = await _stage(database, MERCHANT_TWO_ID, theirs_product)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _list(postgres_client, headers)

    ids = {item["id"] for item in body["items"]}
    assert ids == {str(mine)}
    assert str(applied) not in ids and str(theirs) not in ids


@pytest.mark.asyncio
async def test_list_never_exposes_approval_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """证据只在详情里签发；列表里连字段都不该有（§8.13.3）。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await _stage(database, MERCHANT_ONE_ID, product)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _list(postgres_client, headers)

    assert body["items"]
    for item in body["items"]:
        assert "approval_evidence" not in item
        assert "approval_evidence_expires_at" not in item


@pytest.mark.asyncio
async def test_list_is_sorted_newest_first_and_pages_without_gaps(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    for index in range(5):
        await _stage(database, MERCHANT_ONE_ID, product, delta=10 + index, created_days_ago=index)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    first = await _list(postgres_client, headers, limit=2)
    second = await _list(postgres_client, headers, limit=2, cursor=first["next_cursor"])
    third = await _list(postgres_client, headers, limit=2, cursor=second["next_cursor"])

    seen = [item["created_at"] for page in (first, second, third) for item in page["items"]]
    assert len(seen) == 5
    assert seen == sorted(seen, reverse=True)
    assert third["has_more"] is False


@pytest.mark.asyncio
async def test_list_state_filter_binds_the_cursor(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    for index in range(3):
        await _stage(database, MERCHANT_ONE_ID, product, created_days_ago=index)
        await _stage(
            database, MERCHANT_ONE_ID, product, state=DraftState.APPLIED, created_days_ago=index
        )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    staged = await _list(postgres_client, headers, limit=1)

    applied = await _list(postgres_client, headers, state="APPLIED")
    crossed = await postgres_client.get(
        DRAFTS_PATH,
        headers=headers,
        params={"limit": 1, "state": "APPLIED", "cursor": staged["next_cursor"]},
    )

    assert len(applied["items"]) == 3
    assert crossed.status_code == 422
    assert crossed.json()["code"] == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_discard_is_idempotent(postgres_app: FastAPI, postgres_client: AsyncClient) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    draft = await _stage(database, MERCHANT_ONE_ID, product)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    first = await postgres_client.delete(f"{DRAFTS_PATH}/{draft}", headers=headers)
    second = await postgres_client.delete(f"{DRAFTS_PATH}/{draft}", headers=headers)

    assert first.status_code == second.status_code == 204
    async with database.session() as session:
        assert (await session.get(Draft, draft)).state == "DISCARDED"  # type: ignore[union-attr]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [DraftState.APPLIED, DraftState.EXPIRED])
async def test_terminal_drafts_cannot_be_discarded(
    postgres_app: FastAPI, postgres_client: AsyncClient, state: DraftState
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    draft = await _stage(database, MERCHANT_ONE_ID, product, state=state)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.delete(f"{DRAFTS_PATH}/{draft}", headers=headers)

    assert resp.status_code == 409
    assert resp.json()["code"] == "ILLEGAL_STATE_TRANSITION"
    assert resp.json()["details"] == [{"state": state.value}]


@pytest.mark.asyncio
async def test_cross_shop_discard_is_forbidden(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_TWO_ID)
    theirs = await _stage(database, MERCHANT_TWO_ID, product)
    mine = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.delete(f"{DRAFTS_PATH}/{theirs}", headers=mine)

    assert resp.status_code == 403
    async with database.session() as session:
        assert (await session.get(Draft, theirs)).state == "STAGED"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_detail_of_expired_draft_issues_no_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """过期草稿的两个证据字段必须同时为 null，即使清理任务还没跑。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    # 回溯创建时间而不是把过期时间提前：真实的过期草稿是 7 天前建的，
    # 只改 expires_at 会造出一个「过期早于创建」的草稿，契约模型本来就不接受。
    draft = await _stage(database, MERCHANT_ONE_ID, product, created_days_ago=8)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = (await postgres_client.get(f"{DRAFTS_PATH}/{draft}", headers=headers)).json()

    assert body["approval_evidence"] is None
    assert body["approval_evidence_expires_at"] is None
    # 读取路径同样自检过期并落盘，不等清理任务（§8.13.2）。
    assert body["state"] == "EXPIRED"
    async with database.session() as session:
        assert (await session.get(Draft, draft)).state == "EXPIRED"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_expire_job_only_touches_drafts_past_seven_days(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """任务接受 `now` 参数，不读墙钟；只动超过 7 天的 `STAGED` 草稿。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    fresh = await _stage(database, MERCHANT_ONE_ID, product, created_days_ago=6)
    stale = await _stage(database, MERCHANT_ONE_ID, product, created_days_ago=8)
    applied = await _stage(
        database, MERCHANT_ONE_ID, product, state=DraftState.APPLIED, created_days_ago=8
    )

    expired = await expire_drafts(database, now=datetime.now(UTC))

    assert expired == 1
    async with database.session() as session:
        states = {
            row.id: row.state for row in (await session.execute(select(Draft))).scalars().all()
        }
    assert states[stale] == "EXPIRED"
    assert states[fresh] == "STAGED"
    assert states[applied] == "APPLIED"


@pytest.mark.asyncio
async def test_expire_job_is_idempotent(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await _stage(database, MERCHANT_ONE_ID, product, created_days_ago=8)
    now = datetime.now(UTC)

    first = await expire_drafts(database, now=now)
    second = await expire_drafts(database, now=now)

    assert (first, second) == (1, 0)


@pytest.mark.asyncio
async def test_unknown_draft_id_is_forbidden_not_found(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.delete(f"{DRAFTS_PATH}/{uuid4()}", headers=headers)

    assert resp.status_code == 403
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"
