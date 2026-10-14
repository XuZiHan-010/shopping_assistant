"""上下架草稿端到端（PRD M5）——真实 PostgreSQL。

链路：工具起草 → 审批详情差异 → 批准 → `products.status` 改变并写 `change_ledger`。
另证明：起草后状态被并发改动 → 409；非 ONLINE/OFFLINE 商品起草被护栏拒绝；跨商家不可见。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.models.analytics import Product
from app.models.drafts import ChangeLedger, Draft
from app.repositories.audit import AuditRepository
from app.schemas.v2.drafts import DraftKind, DraftState
from app.services.v2.drafts import DatabaseDraftSink
from app.tools.errors import FatalToolError
from app.tools.gates import AuditRepositorySecurityAudit, DatabaseProvenanceStore, ToolGates
from app.tools.merchant import build_merchant_tools
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext, ToolOutcome
from tests.conftest import (
    MERCHANT_ONE_AUTH,
    MERCHANT_ONE_ID,
    MERCHANT_TWO_AUTH,
    MERCHANT_TWO_ID,
)
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration

DRAFTS_PATH = "/api/v2/merchant/drafts"
CONVERSATION = "conv-listing-1"


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


def _gates(database: Database) -> ToolGates:
    registry = ToolRegistry()
    for spec in build_merchant_tools(database):
        registry.register(spec)
    return ToolGates(
        registry,
        provenance=DatabaseProvenanceStore(database),
        principal_secret=b"integration-principal-secret",
        audit=AuditRepositorySecurityAudit(AuditRepository(database)),
        drafts=DatabaseDraftSink(database),
    )


def _ctx(merchant_id: UUID) -> ToolContext:
    session = SessionContext(
        session_record_id=UUID("00000000-0000-0000-0000-00000000c001"),
        role=SessionRole.MERCHANT,
        merchant_id=merchant_id,
        buyer_key=None,
        shop_slug=None,
    )
    return ToolContext(session=session, conversation_id=CONVERSATION, request_id="req-listing-1")


async def _see(gates: ToolGates, ctx: ToolContext, product: UUID) -> None:
    """来源闸门：先让本对话「见过」该商品（读取商品记录的工具会产出商品引用）。"""

    result = await gates.invoke(ctx, "get_product_content", {"product_id": str(product)})
    assert result.ok


async def _draft(
    database: Database, merchant_id: UUID, product: UUID, action: str
) -> tuple[Any, UUID | None]:
    gates = _gates(database)
    ctx = _ctx(merchant_id)
    await _see(gates, ctx, product)
    result = await gates.invoke(
        ctx, "draft_listing_status", {"product_id": str(product), "action": action}
    )
    if not result.ok:
        return result, None
    async with database.session() as session:
        draft = (
            (await session.execute(select(Draft).where(Draft.target_id == product)))
            .scalars()
            .one()
        )
        return result, draft.id


async def _status(database: Database, product: UUID) -> str:
    async with database.session() as session:
        return str((await session.get(Product, product)).status)  # type: ignore[union-attr]


async def _set_status(database: Database, product: UUID, status: str) -> None:
    async with database.session() as session:
        await session.execute(update(Product).where(Product.id == product).values(status=status))
        await session.commit()


async def _detail(client: AsyncClient, headers: dict[str, str], draft_id: UUID) -> dict[str, Any]:
    resp = await client.get(f"{DRAFTS_PATH}/{draft_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


async def _apply(
    client: AsyncClient, headers: dict[str, str], draft_id: UUID, detail: dict[str, Any]
) -> Any:
    return await client.post(
        f"{DRAFTS_PATH}/{draft_id}/apply",
        json={
            "client_request_id": f"apply-{draft_id}",
            "draft_version": detail["draft_version"],
            "target_version": detail["target_version"],
            "approval_evidence": detail["approval_evidence"],
        },
        headers=headers,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "start", "end", "version", "title_prefix"),
    [
        ("PAUSE", "ONLINE", "OFFLINE", 1, "下架："),
        ("ACTIVATE", "OFFLINE", "ONLINE", 0, "重新上架："),
    ],
)
async def test_draft_then_approve_changes_status_and_writes_ledger(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
    action: str,
    start: str,
    end: str,
    version: int,
    title_prefix: str,
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="木质书架", status=start)

    result, draft_id = await _draft(database, MERCHANT_ONE_ID, product, action)

    assert result.outcome is ToolOutcome.DRAFT_CREATED and draft_id is not None
    # 起草只生成草稿，商品状态不变。
    assert await _status(database, product) == start
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    detail = await _detail(postgres_client, headers, draft_id)
    assert detail["kind"] == DraftKind.LISTING_STATUS.value
    assert detail["title"] == f"{title_prefix}木质书架"
    assert detail["target_version"] == version
    [entry] = detail["diff"]["entries"]
    assert entry["entry_id"] == f"{draft_id}:status"
    assert (entry["field"], entry["unit"], entry["is_preview"]) == ("status", "TEXT", False)
    assert (entry["before"], entry["after"]) == (start, end)
    assert detail["guardrail_checks"][0]["code"] == "LISTING_STATUS_NOT_TOGGLEABLE"

    resp = await _apply(postgres_client, headers, draft_id, detail)

    assert resp.status_code == 200, resp.text
    assert resp.json()["draft"]["state"] == DraftState.APPLIED.value
    assert resp.json()["ledger_entry"]["applied_entry_ids"] == [entry["entry_id"]]
    assert await _status(database, product) == end
    async with database.session() as session:
        ledger = (await session.execute(select(ChangeLedger))).scalars().one()
        assert ledger.draft_id == draft_id
    assert resp.json()["ledger_entry"]["kind"] == DraftKind.LISTING_STATUS.value


@pytest.mark.asyncio
async def test_status_changed_after_drafting_conflicts_with_409(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, status="ONLINE")
    _, draft_id = await _draft(database, MERCHANT_ONE_ID, product, "PAUSE")
    assert draft_id is not None
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    detail = await _detail(postgres_client, headers, draft_id)
    await _set_status(database, product, "OFFLINE")  # 起草后被别处下架

    resp = await _apply(postgres_client, headers, draft_id, detail)

    assert resp.status_code == 409, resp.text
    async with database.session() as session:
        assert (await session.get(Draft, draft_id)).state == "STAGED"  # type: ignore[union-attr]
        assert (await session.execute(select(ChangeLedger))).scalars().all() == []
    assert await _status(database, product) == "OFFLINE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "status"),
    [("PAUSE", "AUDITING"), ("PAUSE", "OFFLINE"), ("ACTIVATE", "ONLINE"), ("ACTIVATE", "REJECTED")],
)
async def test_untoggleable_status_is_rejected_by_guardrail(
    postgres_app: FastAPI, action: str, status: str
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, status=status)

    result, draft_id = await _draft(database, MERCHANT_ONE_ID, product, action)

    assert draft_id is None and not result.ok
    assert result.guardrail is not None
    assert result.guardrail.code == "LISTING_STATUS_NOT_TOGGLEABLE"
    assert result.guardrail.current_limit and result.guardrail.remediation
    async with database.session() as session:
        assert (await session.execute(select(Draft))).scalars().all() == []
    assert await _status(database, product) == status


@pytest.mark.asyncio
async def test_other_merchants_product_cannot_be_drafted_or_seen(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    theirs = await seed_product(database, MERCHANT_TWO_ID, status="ONLINE")
    gates = _gates(database)
    ctx = _ctx(MERCHANT_ONE_ID)

    with pytest.raises(FatalToolError):
        await gates.invoke(
            ctx, "draft_listing_status", {"product_id": str(theirs), "action": "PAUSE"}
        )

    # 商家二自己起草的草稿，商家一读不到（R5：不泄露存在性）。
    _, draft_id = await _draft(database, MERCHANT_TWO_ID, theirs, "PAUSE")
    assert draft_id is not None
    one = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    resp = await postgres_client.get(f"{DRAFTS_PATH}/{draft_id}", headers=one)
    assert resp.status_code in (403, 404)
    two = await merchant_session_headers(postgres_client, MERCHANT_TWO_AUTH)
    assert (await postgres_client.get(f"{DRAFTS_PATH}/{draft_id}", headers=two)).status_code == 200
