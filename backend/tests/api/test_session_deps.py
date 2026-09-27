"""v2 会话依赖：跨角色门禁、统一错误码与审计（真实 PostgreSQL）。"""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.api.session_deps import (
    require_bound_customer_session,
    require_customer_session,
    require_merchant_session,
)
from app.core.security import MerchantContext
from app.core.session import SessionContext
from app.db.session import Database
from app.models.operations import AuditLog
from app.repositories.session import SessionRepository
from tests.conftest import MERCHANT_ONE_ID

DEFAULT_TTL = 86_400


def _mount_probes(app: FastAPI) -> None:
    @app.get("/probe/customer")
    async def customer_probe(
        ctx: Annotated[SessionContext, Depends(require_customer_session)],
    ) -> dict[str, str]:
        return {"role": ctx.role.value}

    @app.get("/probe/merchant")
    async def merchant_probe(
        ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    ) -> dict[str, str]:
        return {"role": ctx.role.value}

    @app.get("/probe/bound-customer")
    async def bound_customer_probe(
        ctx: Annotated[SessionContext, Depends(require_bound_customer_session)],
    ) -> dict[str, str]:
        return {"role": ctx.role.value, "buyer_key": ctx.buyer_key or ""}


async def _issue_customer_token(database: Database, *, bound: bool = False) -> str:
    async with database.session() as session:
        repo = SessionRepository(session, default_ttl_seconds=DEFAULT_TTL)
        token, ctx = await repo.issue_customer_guest(
            merchant_id=MERCHANT_ONE_ID, shop_slug="borough-100"
        )
        if bound:
            await repo.bind_demo_customer(ctx, buyer_key="demo-buyer-1")
        await session.commit()
        return token


async def _issue_merchant_token(database: Database) -> str:
    async with database.session() as session:
        repo = SessionRepository(session, default_ttl_seconds=DEFAULT_TTL)
        token, _ = await repo.issue_merchant(
            MerchantContext(merchant_id=MERCHANT_ONE_ID), issuer="demo-token-A"
        )
        await session.commit()
        return token


@pytest.mark.asyncio
async def test_missing_header_returns_session_required(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _mount_probes(postgres_app)

    resp = await postgres_client.get("/probe/customer")

    assert resp.status_code == 401
    assert resp.json()["code"] == "SESSION_REQUIRED"


@pytest.mark.asyncio
async def test_garbage_token_returns_session_invalid(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _mount_probes(postgres_app)

    resp = await postgres_client.get(
        "/probe/customer", headers={"X-Session-Id": "not-a-real-token"}
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == "SESSION_INVALID"


@pytest.mark.asyncio
async def test_customer_session_calling_merchant_endpoint_is_forbidden_and_audited(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _mount_probes(postgres_app)
    database: Database = postgres_app.state.database
    token = await _issue_customer_token(database)

    resp = await postgres_client.get(
        "/probe/merchant",
        headers={"X-Session-Id": token, "X-Request-Id": "req-customer-to-merchant"},
    )

    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "SESSION_ROLE_MISMATCH"
    assert body["details"] == []

    async with database.session() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.request_id == "req-customer-to-merchant")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].event_type == "SESSION_ROLE_MISMATCH"
    dumped = str(rows[0].event_metadata)
    assert token not in dumped


@pytest.mark.asyncio
async def test_merchant_session_calling_customer_endpoint_is_forbidden_and_audited(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _mount_probes(postgres_app)
    database: Database = postgres_app.state.database
    token = await _issue_merchant_token(database)

    resp = await postgres_client.get(
        "/probe/customer",
        headers={"X-Session-Id": token, "X-Request-Id": "req-merchant-to-customer"},
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"

    async with database.session() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.request_id == "req-merchant-to-customer")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_unbound_customer_calling_bound_endpoint_requires_binding(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _mount_probes(postgres_app)
    database: Database = postgres_app.state.database
    token = await _issue_customer_token(database, bound=False)

    resp = await postgres_client.get("/probe/bound-customer", headers={"X-Session-Id": token})

    assert resp.status_code == 403
    assert resp.json()["code"] == "CUSTOMER_BINDING_REQUIRED"


@pytest.mark.asyncio
async def test_bound_customer_passes_bound_guard(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _mount_probes(postgres_app)
    database: Database = postgres_app.state.database
    token = await _issue_customer_token(database, bound=True)

    resp = await postgres_client.get("/probe/bound-customer", headers={"X-Session-Id": token})

    assert resp.status_code == 200
    assert resp.json() == {"role": "CUSTOMER", "buyer_key": "demo-buyer-1"}


@pytest.mark.asyncio
async def test_matching_role_passes_through(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _mount_probes(postgres_app)
    database: Database = postgres_app.state.database
    customer_token = await _issue_customer_token(database)
    merchant_token = await _issue_merchant_token(database)

    customer_resp = await postgres_client.get(
        "/probe/customer", headers={"X-Session-Id": customer_token}
    )
    merchant_resp = await postgres_client.get(
        "/probe/merchant", headers={"X-Session-Id": merchant_token}
    )

    assert customer_resp.status_code == 200
    assert customer_resp.json() == {"role": "CUSTOMER"}
    assert merchant_resp.status_code == 200
    assert merchant_resp.json() == {"role": "MERCHANT"}
