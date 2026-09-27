"""5 条会话签发路由的 HTTP 契约与跨角色门禁（真实 PostgreSQL，模块 D Task 7）。"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.core.errors import DatabaseUnavailableError
from app.db.session import Database
from app.main import create_app
from app.models.operations import AuditLog
from app.repositories.session import SessionRepository
from tests.conftest import (
    MERCHANT_ONE_AUTH,
    MERCHANT_ONE_ID,
    MERCHANT_ONE_TOKEN,
    MERCHANT_TWO_AUTH,
    MERCHANT_TWO_TOKEN,
)
from tests.support.log_capture import reenable_app_logger

SHOP_SLUG = "borough-api-100"
DEFAULT_TTL = 86_400


def _enable_demo_customer(app: FastAPI, *, buyer_key: str = "demo-buyer-1") -> None:
    app.state.settings.demo_deployment_mode = True
    app.state.settings.demo_customer_identities = {SHOP_SLUG: buyer_key}


async def _create_guest_session(client: AsyncClient) -> dict[str, Any]:
    resp = await client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP_SLUG})
    assert resp.status_code == 201, resp.text
    return dict(resp.json())


@pytest.mark.asyncio
async def test_create_shop_session_succeeds_with_no_store(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    resp = await postgres_client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP_SLUG})

    assert resp.status_code == 201
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["role"] == "CUSTOMER"
    assert len(body["session_id"]) >= 43


@pytest.mark.asyncio
async def test_create_shop_session_unknown_slug_is_forbidden(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    resp = await postgres_client.post("/api/v2/shop/sessions", json={"shop_slug": "no-such-shop"})

    assert resp.status_code == 403
    assert resp.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.asyncio
async def test_create_shop_session_rejects_extra_body_fields(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    resp = await postgres_client.post(
        "/api/v2/shop/sessions",
        json={"shop_slug": SHOP_SLUG, "merchant_id": "00000000-0000-0000-0000-000000000001"},
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_demo_customer_bind_disabled_when_demo_mode_off(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    postgres_app.state.settings.demo_deployment_mode = False
    guest = await _create_guest_session(postgres_client)

    resp = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer",
        json={},
        headers={"X-Session-Id": guest["session_id"]},
    )

    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_demo_customer_bind_succeeds_and_sets_cart_adjusted_false(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _enable_demo_customer(postgres_app)
    guest = await _create_guest_session(postgres_client)

    resp = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer",
        json={},
        headers={"X-Session-Id": guest["session_id"]},
    )

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["is_bound"] is True
    assert body["cart_adjusted"] is False


@pytest.mark.asyncio
async def test_demo_customer_rebind_same_identity_is_idempotent(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _enable_demo_customer(postgres_app)
    guest = await _create_guest_session(postgres_client)
    headers = {"X-Session-Id": guest["session_id"]}

    first = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer", json={}, headers=headers
    )
    second = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer", json={}, headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 200


@pytest.mark.asyncio
async def test_revoke_shop_session_then_reuse_is_invalid(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    guest = await _create_guest_session(postgres_client)
    headers = {"X-Session-Id": guest["session_id"]}

    revoke = await postgres_client.delete("/api/v2/shop/sessions/current", headers=headers)
    assert revoke.status_code == 204

    reuse = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer", json={}, headers=headers
    )
    assert reuse.status_code == 401
    assert reuse.json()["code"] == "SESSION_INVALID"


@pytest.mark.asyncio
async def test_merchant_session_calling_shop_bind_is_forbidden_and_audited(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _enable_demo_customer(postgres_app)
    merchant_resp = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_ONE_AUTH
    )
    merchant_token = merchant_resp.json()["session_id"]

    resp = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer",
        json={},
        headers={"X-Session-Id": merchant_token, "X-Request-Id": "req-v2-merchant-to-shop"},
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"

    database: Database = postgres_app.state.database
    async with database.session() as session:
        rows = (
            (
                await session.execute(
                    select(AuditLog).where(AuditLog.request_id == "req-v2-merchant-to-shop")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_shop_session_calling_merchant_revoke_is_forbidden(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    guest = await _create_guest_session(postgres_client)

    resp = await postgres_client.delete(
        "/api/v2/merchant/sessions/current", headers={"X-Session-Id": guest["session_id"]}
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "SESSION_ROLE_MISMATCH"


@pytest.mark.asyncio
async def test_create_merchant_session_succeeds_with_display_name(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    resp = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_ONE_AUTH
    )

    assert resp.status_code == 201
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["role"] == "MERCHANT"
    assert body["merchant_display_name"]


@pytest.mark.asyncio
async def test_revoke_merchant_session_then_reuse_is_invalid(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    create = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_ONE_AUTH
    )
    token = create.json()["session_id"]
    headers = {"X-Session-Id": token}

    revoke = await postgres_client.delete("/api/v2/merchant/sessions/current", headers=headers)
    assert revoke.status_code == 204

    reuse = await postgres_client.delete("/api/v2/merchant/sessions/current", headers=headers)
    assert reuse.status_code == 401
    assert reuse.json()["code"] == "SESSION_INVALID"


@pytest.mark.asyncio
async def test_revoking_demo_token_invalidates_its_merchant_sessions(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """D8⑤：撤销演示 Token 后，由它换取的商家会话失效。"""

    create = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_ONE_AUTH
    )
    token = create.json()["session_id"]

    database: Database = postgres_app.state.database
    async with database.session() as session:
        repo = SessionRepository(session, default_ttl_seconds=DEFAULT_TTL)
        revoked = await repo.revoke_by_issuer(
            MERCHANT_ONE_AUTH["Authorization"].removeprefix("Bearer ")
        )
        await session.commit()
    assert revoked >= 1

    resp = await postgres_client.delete(
        "/api/v2/merchant/sessions/current", headers={"X-Session-Id": token}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "SESSION_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_initial_connection", [False, True])
async def test_startup_reconciliation_revokes_sessions_of_removed_demo_tokens(
    postgres_app: FastAPI,
    postgres_client: AsyncClient,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    fail_initial_connection: bool,
) -> None:
    """Astra D3：从 DEMO_MERCHANT_TOKENS 删掉某个 Token 并重启后，它换出的会话失效。"""

    reenable_app_logger()
    caplog.set_level(logging.INFO)
    kept = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_ONE_AUTH
    )
    removed = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_TWO_AUTH
    )
    assert kept.status_code == removed.status_code == 201

    restarted_settings = postgres_app.state.settings.model_copy(
        update={"demo_merchant_tokens": {MERCHANT_ONE_TOKEN: MERCHANT_ONE_ID}}
    )
    restarted = create_app(restarted_settings, database=Database(restarted_settings))
    if fail_initial_connection:
        from unittest.mock import AsyncMock

        database = restarted.state.database
        original_connect = database.connect_with_retry
        monkeypatch.setattr(
            database, "connect_with_retry", AsyncMock(side_effect=DatabaseUnavailableError())
        )
        with pytest.raises(DatabaseUnavailableError):
            async with restarted.router.lifespan_context(restarted):
                pytest.fail("数据库失联时不能跳过身份对账开放请求")
        monkeypatch.setattr(database, "connect_with_retry", original_connect)
    async with restarted.router.lifespan_context(restarted):
        pass

    revoked_resp = await postgres_client.delete(
        "/api/v2/merchant/sessions/current",
        headers={"X-Session-Id": removed.json()["session_id"]},
    )
    kept_resp = await postgres_client.delete(
        "/api/v2/merchant/sessions/current",
        headers={"X-Session-Id": kept.json()["session_id"]},
    )
    assert revoked_resp.status_code == 401
    assert revoked_resp.json()["code"] == "SESSION_INVALID"
    assert kept_resp.status_code == 204

    assert "session_issuers_reconciled" in caplog.text
    assert "revoked_sessions=1" in caplog.text
    for secret in (MERCHANT_ONE_TOKEN, MERCHANT_TWO_TOKEN):
        assert secret not in caplog.text


@pytest.mark.asyncio
async def test_no_plaintext_session_id_in_logs_or_audit(
    postgres_app: FastAPI, postgres_client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    reenable_app_logger()
    caplog.set_level(logging.INFO)
    _enable_demo_customer(postgres_app)
    merchant_resp = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_ONE_AUTH
    )
    merchant_token = merchant_resp.json()["session_id"]

    resp = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer",
        json={},
        headers={"X-Session-Id": merchant_token, "X-Request-Id": "req-v2-no-leak"},
    )
    assert resp.status_code == 403

    database: Database = postgres_app.state.database
    async with database.session() as session:
        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.request_id == "req-v2-no-leak")))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    dumped = str(rows[0].event_metadata)
    assert merchant_token not in dumped

    # 先确认日志确实被捕获到了，否则下面的"不含明文"是恒真断言。
    assert "req-v2-no-leak" in caplog.text
    assert merchant_token not in caplog.text


@pytest.mark.asyncio
async def test_second_merchant_cannot_reuse_first_merchant_session(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """跨商家：第二家商家的 Token 换取的会话不应影响第一家的会话可见性。"""

    first = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_ONE_AUTH
    )
    second = await postgres_client.post(
        "/api/v2/merchant/sessions", json={}, headers=MERCHANT_TWO_AUTH
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["session_id"] != second.json()["session_id"]


@pytest.mark.asyncio
async def test_rebind_different_identity_returns_conflict(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _enable_demo_customer(postgres_app)
    guest = await _create_guest_session(postgres_client)
    headers = {"X-Session-Id": guest["session_id"]}
    first = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer", json={}, headers=headers
    )
    assert first.status_code == 200
    _enable_demo_customer(postgres_app, buyer_key="another-buyer")
    conflict = await postgres_client.post(
        "/api/v2/shop/sessions/demo-customer", json={}, headers=headers
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "SESSION_ALREADY_BOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["BEARER", "bEaReR"])
async def test_mixed_case_bearer_session_survives_reconciliation(
    postgres_app: FastAPI, postgres_client: AsyncClient, scheme: str
) -> None:
    from app.services.session_reconciliation import reconcile_demo_issuers

    created = await postgres_client.post(
        "/api/v2/merchant/sessions",
        json={},
        headers={"Authorization": f"{scheme} {MERCHANT_ONE_TOKEN}"},
    )
    assert created.status_code == 201
    await reconcile_demo_issuers(postgres_app.state.database, postgres_app.state.settings)
    response = await postgres_client.delete(
        "/api/v2/merchant/sessions/current",
        headers={"X-Session-Id": created.json()["session_id"]},
    )
    assert response.status_code == 204
