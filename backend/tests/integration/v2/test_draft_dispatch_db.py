"""草稿应用按种类分派（N3 阶段 A Task 5）——走真实路由与 PostgreSQL。

用 `monkeypatch` 把分派表换成替身处理器，证明两件骨架必须保证的事：

1. 处理器拿到的请求里没有审批证据（证据在骨架里、同一事务中消费）；
2. 处理器在第 6 步拒绝 → 证据消费随事务回滚，草稿保持 `STAGED`，不写账本。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import GuardrailRejectedError
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.models.drafts import ChangeLedger, Draft
from app.models.operations import OperationEvidenceNonce
from app.schemas.v2.drafts import DraftKind
from app.services.v2 import draft_apply
from app.services.v2.draft_handlers import HandlerRequest, HandlerResult
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.integration.v2.test_draft_apply import (
    _apply,
    _database,
    _draft_state,
    _evidence,
    _stage_restock,
)
from tests.support.merchant_v2 import merchant_session_headers, seed_product

pytestmark = pytest.mark.integration


@dataclass
class SpyHandler:
    kind: DraftKind = DraftKind.RESTOCK
    seen: list[HandlerRequest] = field(default_factory=list)

    async def apply(
        self,
        session: AsyncSession,
        ctx: SessionContext,
        draft: Draft,
        request: HandlerRequest,
        *,
        now: datetime,
        locale: SupportedLocale,
    ) -> HandlerResult:
        self.seen.append(request)
        return HandlerResult(checks=[], applied_entry_ids=[f"{draft.id}:spy"])


@dataclass
class FailingHandler:
    kind: DraftKind = DraftKind.RESTOCK

    async def apply(
        self,
        session: AsyncSession,
        ctx: SessionContext,
        draft: Draft,
        request: HandlerRequest,
        *,
        now: datetime,
        locale: SupportedLocale,
    ) -> HandlerResult:
        raise GuardrailRejectedError(
            details=[
                {
                    "code": "RESTOCK_DELTA_LIMIT",
                    "passed": False,
                    "current_limit": "单次补货上限 10",
                    "remediation": "把补货量降到 10 以内",
                }
            ]
        )


async def _nonce_count(app: FastAPI) -> int:
    async with _database(app).session() as session:
        return int(await session.scalar(select(func.count()).select_from(OperationEvidenceNonce)))


async def _ledger_count(app: FastAPI, draft_id: Any) -> int:
    async with _database(app).session() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(ChangeLedger)
                .where(ChangeLedger.draft_id == draft_id)
            )
        )


@pytest.mark.asyncio
async def test_handler_cannot_see_approval_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = SpyHandler()
    monkeypatch.setattr(draft_apply, "HANDLERS", {DraftKind.RESTOCK: spy})
    db = _database(postgres_app)
    pid = await seed_product(db, MERCHANT_ONE_ID, on_hand=12)
    did = await _stage_restock(db, MERCHANT_ONE_ID, pid, delta=5, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, did)

    response = await _apply(postgres_client, headers, did, evidence=evidence)

    assert response.status_code == 200, response.text
    (seen,) = spy.seen
    assert "approval_evidence" not in {f.name for f in fields(seen)}
    assert evidence not in repr(seen)
    assert (seen.draft_version, seen.target_version, seen.accepted_entry_ids) == (1, 12, None)
    # 骨架负责置 APPLIED 与写账本；账本里的条目 ID 来自处理器
    body = response.json()
    assert body["draft"]["state"] == "APPLIED"
    assert body["ledger_entry"]["applied_entry_ids"] == [f"{did}:spy"]
    assert await _ledger_count(postgres_app, did) == 1


@pytest.mark.asyncio
async def test_handler_failure_rolls_back_evidence(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """处理器在第 6 步抛护栏拒绝 → 证据消费随事务回滚，草稿仍 STAGED。"""
    monkeypatch.setattr(draft_apply, "HANDLERS", {DraftKind.RESTOCK: FailingHandler()})
    db = _database(postgres_app)
    pid = await seed_product(db, MERCHANT_ONE_ID, on_hand=12)
    did = await _stage_restock(db, MERCHANT_ONE_ID, pid, delta=5, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, did)
    before = await _nonce_count(postgres_app)

    response = await _apply(postgres_client, headers, did, evidence=evidence)

    assert response.status_code == 422
    assert response.json()["code"] == "GUARDRAIL_REJECTED"
    assert await _nonce_count(postgres_app) == before
    assert await _draft_state(db, did) == "STAGED"
    assert await _ledger_count(postgres_app, did) == 0


@pytest.mark.asyncio
async def test_unregistered_kind_is_a_deployment_defect_not_a_user_error(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """表里没有该种类 → 500（RuntimeError），不是 409/422；且不消费证据、不推进状态。"""
    monkeypatch.setattr(draft_apply, "HANDLERS", {})
    db = _database(postgres_app)
    pid = await seed_product(db, MERCHANT_ONE_ID, on_hand=12)
    did = await _stage_restock(db, MERCHANT_ONE_ID, pid, delta=5, base=12)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    evidence = await _evidence(postgres_client, headers, did)
    before = await _nonce_count(postgres_app)

    # 未处理异常由全局处理器转成 500 后，Starlette 仍会向外重抛；换一个不重抛的传输层看响应。
    async with AsyncClient(
        transport=ASGITransport(app=postgres_app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await _apply(client, headers, did, evidence=evidence)

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert await _nonce_count(postgres_app) == before
    assert await _draft_state(db, did) == "STAGED"
