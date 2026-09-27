"""安全硬门禁：统一 403 非枚举响应与双重过滤（PRD §12.1，R5，O1）。"""

from __future__ import annotations

import os
import statistics
import time
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import MerchantContext
from app.db.session import Database
from app.models.analytics import Order, Product
from app.models.operations import AuditLog
from app.repositories.session import SessionRepository
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.scope_probe import ScopeProbeRepository, mount_scope_probe

DEFAULT_TTL = 86_400


def _product(merchant_id: UUID, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid4(),
        "merchant_id": merchant_id,
        "business_date": date(2026, 9, 22),
        "product_code": f"p-{uuid4().hex}",
        "title": "测试商品",
        "category": "测试",
        "price": Decimal("10.00"),
        "status": "ONLINE",
        "listed_at": datetime.now(UTC),
    }
    values.update(overrides)
    return values


def _order(merchant_id: UUID, buyer_key: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "id": uuid4(),
        "merchant_id": merchant_id,
        "business_date": date(2026, 9, 22),
        "order_no": f"o-{uuid4().hex}",
        "buyer_key": buyer_key,
        "order_status": "CREATED",
        "payment_status": "PENDING",
        "fulfillment_status": "NOT_SHIPPED",
        "after_sale_status": "NONE",
        "lifecycle_origin": "V2",
        "total_amount": Decimal("10.00"),
        "paid_amount": Decimal("0.00"),
        "placed_at": datetime.now(UTC),
    }
    values.update(overrides)
    return values


async def _issue_merchant_token(database: Database, merchant_id: UUID, *, issuer: str) -> str:
    async with database.session() as session:
        repo = SessionRepository(session, default_ttl_seconds=DEFAULT_TTL)
        token, _ = await repo.issue_merchant(
            MerchantContext(merchant_id=merchant_id), issuer=issuer
        )
        await session.commit()
        return token


@pytest.fixture
def scope_probe_app(postgres_app: FastAPI) -> FastAPI:
    mount_scope_probe(postgres_app)
    return postgres_app


@pytest_asyncio.fixture
async def scope_probe_client(scope_probe_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=scope_probe_app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_missing_and_foreign_resources_are_field_identical(
    scope_probe_app: FastAPI,
    scope_probe_client: AsyncClient,
) -> None:
    database: Database = scope_probe_app.state.database
    async with database.session() as session:
        foreign_product = _product(MERCHANT_TWO_ID)
        session.add(Product(**foreign_product))
        await session.commit()

    token = await _issue_merchant_token(database, MERCHANT_ONE_ID, issuer="demo-token-scope-a")
    missing_id = uuid4()
    headers = {"X-Session-Id": token, "X-Request-Id": "scope-parity-probe"}

    missing = await scope_probe_client.get(f"/scope-probe/{missing_id}", headers=headers)
    foreign = await scope_probe_client.get(f"/scope-probe/{foreign_product['id']}", headers=headers)

    assert missing.status_code == foreign.status_code == 403
    assert missing.json() == foreign.json()
    assert missing.headers == foreign.headers
    assert missing.json()["code"] == "RESOURCE_FORBIDDEN"
    assert missing.json()["details"] == []


@pytest.mark.asyncio
async def test_cross_merchant_access_is_forbidden_and_audited(
    scope_probe_app: FastAPI,
    scope_probe_client: AsyncClient,
) -> None:
    database: Database = scope_probe_app.state.database
    async with database.session() as session:
        foreign_product = _product(MERCHANT_TWO_ID)
        session.add(Product(**foreign_product))
        await session.commit()

    token = await _issue_merchant_token(database, MERCHANT_ONE_ID, issuer="demo-token-scope-b")

    resp = await scope_probe_client.get(
        f"/scope-probe/{foreign_product['id']}",
        headers={"X-Session-Id": token, "X-Request-Id": "audit-probe"},
    )

    assert resp.status_code == 403
    async with database.session() as session:
        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.request_id == "audit-probe")))
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].event_type == "RESOURCE_SCOPE_VIOLATION"
    metadata = str(rows[0].event_metadata)
    assert token not in metadata
    assert str(foreign_product["id"]) in str(rows[0].resource_id)


@pytest.mark.asyncio
async def test_customer_queries_always_double_filter(postgres_app: FastAPI) -> None:
    """D7①：订单查询强制 `merchant_id` + `buyer_key` 双重过滤，跨店也要挡。"""

    database: Database = postgres_app.state.database
    buyer_a = "buyer-a"
    async with database.session() as session:
        own_order = _order(MERCHANT_ONE_ID, buyer_a)
        other_buyer_order = _order(MERCHANT_ONE_ID, "buyer-b")
        other_shop_order = _order(MERCHANT_TWO_ID, buyer_a)
        session.add_all([Order(**own_order), Order(**other_buyer_order), Order(**other_shop_order)])
        await session.commit()

        repo = ScopeProbeRepository(session)
        rows = await repo.list_orders_for_customer(merchant_id=MERCHANT_ONE_ID, buyer_key=buyer_a)

    ids = {row.id for row in rows}
    assert ids == {own_order["id"]}
    assert other_buyer_order["id"] not in ids
    assert other_shop_order["id"] not in ids


@pytest.mark.asyncio
@pytest.mark.security_timing
@pytest.mark.skipif(
    os.getenv("REQUIRE_SECURITY_TIMING") != "1",
    reason="时序哨兵只在独占 PostgreSQL 的 security-timing job 中运行",
)
async def test_no_timing_side_channel(
    scope_probe_app: FastAPI,
    scope_probe_client: AsyncClient,
) -> None:
    """PRD §12.1：独占 PostgreSQL 中各 500 次，中位数差 <=10ms，p95 比 0.8-1.25。"""

    database: Database = scope_probe_app.state.database
    async with database.session() as session:
        foreign_product = _product(MERCHANT_TWO_ID)
        session.add(Product(**foreign_product))
        await session.commit()

    token = await _issue_merchant_token(database, MERCHANT_ONE_ID, issuer="demo-token-scope-timing")
    headers = {"X-Session-Id": token}
    missing_url = f"/scope-probe/{uuid4()}"
    foreign_url = f"/scope-probe/{foreign_product['id']}"

    async def one(url: str) -> float:
        t0 = time.perf_counter_ns()
        response = await scope_probe_client.get(url, headers=headers)
        assert response.status_code == 403
        return (time.perf_counter_ns() - t0) / 1_000_000

    for _ in range(20):
        await one(missing_url)
        await one(foreign_url)

    missing_ms: list[float] = []
    foreign_ms: list[float] = []
    for _ in range(500):
        missing_ms.append(await one(missing_url))
        foreign_ms.append(await one(foreign_url))

    median_delta = abs(statistics.median(missing_ms) - statistics.median(foreign_ms))
    missing_p95 = statistics.quantiles(missing_ms, n=100)[94]
    foreign_p95 = statistics.quantiles(foreign_ms, n=100)[94]
    assert median_delta <= 10.0
    assert 0.8 <= missing_p95 / foreign_p95 <= 1.25
