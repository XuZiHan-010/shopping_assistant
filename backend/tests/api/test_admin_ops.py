"""GET /api/admin/ops/status：401/403/200/未配置时 404。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import AppEnvironment, Settings
from app.db.session import Database
from app.main import create_app
from app.repositories.llm_budget import DailyBudgetSnapshot, LlmOpsOverview, TurnStats
from tests.conftest import MERCHANT_ONE_TOKEN
from tests.postgres import truncate_all_tables

ADMIN_TOKEN = "test-only-admin-token-value"

OPS_STATUS_FIELDS = {
    "llm_tokens_used_today",
    "llm_tokens_remaining_today",
    "llm_calls_today",
    "rate_limit_hits",
    "degraded_count",
    "error_code_counts",
    "agent_node_average_ms",
    "demo_deployment_mode",
    # N5 B Task 3（PRD §10.2、§10.4）
    "budget_levels",
    "llm_cost_today",
    "unpriced_calls_today",
    "cache_hit_tokens_today",
    "cache_hit_rate_today",
    "tool_calls_total",
    "tool_errors_total",
    "route_p95_ms",
    # 2026-10-04：每回合统计与降级原因（验收 §12.6）
    "turns_today",
    "avg_tokens_per_turn_today",
    "avg_cost_per_turn_today",
    "avg_turn_elapsed_ms_today",
    "degraded_reason_counts",
    "source_degraded_counts",
}


class FakeLlmBudgetRepository:
    def __init__(self, database: Database) -> None:
        del database

    async def snapshot(self, *, usage_date: object) -> DailyBudgetSnapshot:
        del usage_date
        return DailyBudgetSnapshot(consumed_tokens=0, call_count=0)

    async def ops_overview(self, *, usage_date: object) -> LlmOpsOverview:
        del usage_date
        return LlmOpsOverview(
            scope_usage={},
            cost_by_currency={},
            unpriced_calls=0,
            cache_hit_tokens=0,
            input_tokens=0,
        )

    async def turn_stats(self, **_: object) -> TurnStats:
        return TurnStats(turns=0, agent_tokens=0, agent_cost_by_currency={}, avg_elapsed_ms=None)


def _ops_status_app(monkeypatch: pytest.MonkeyPatch, *, demo_deployment_mode: bool) -> FastAPI:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
        llm_daily_budget_tokens=5_000,
        demo_deployment_mode=demo_deployment_mode,
    )
    monkeypatch.setattr("app.api.routes.admin.LlmBudgetRepository", FakeLlmBudgetRepository)
    return create_app(settings)


def _settings_without_admin_token() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )


def _settings_with_admin_token() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
    )


@pytest.mark.asyncio
async def test_route_absent_when_admin_token_not_configured() -> None:
    app = create_app(_settings_without_admin_token())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_header_returns_401() -> None:
    app = create_app(_settings_with_admin_token())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_merchant_token_used_as_admin_header_returns_403() -> None:
    app = create_app(_settings_with_admin_token())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/admin/ops/status", headers={"X-Admin-Token": MERCHANT_ONE_TOKEN}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


@pytest_asyncio.fixture
async def admin_app(migrated_postgres: str) -> AsyncIterator[FastAPI]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
        llm_daily_budget_tokens=5_000,
    )
    database = Database(settings)
    async with database.session() as session:
        await truncate_all_tables(session)
        await session.execute(text("TRUNCATE TABLE llm_daily_budget CASCADE"))
        await session.commit()
    app = create_app(settings, database=database)
    yield app
    await database.dispose()


@pytest.fixture
def demo_deployment_admin_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    return _ops_status_app(monkeypatch, demo_deployment_mode=True)


@pytest.fixture
def default_admin_ops_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    return _ops_status_app(monkeypatch, demo_deployment_mode=False)


@pytest.mark.asyncio
async def test_correct_token_returns_200_with_safe_payload(admin_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == OPS_STATUS_FIELDS
    assert body["llm_tokens_used_today"] == 0
    assert body["llm_tokens_remaining_today"] == 5_000
    assert ADMIN_TOKEN not in response.text
    assert "postgresql" not in response.text.lower()
    assert MERCHANT_ONE_TOKEN not in response.text
    assert body["demo_deployment_mode"] is False


@pytest.mark.asyncio
async def test_ops_status_reports_explicit_demo_deployment_mode_without_sensitive_configuration(
    demo_deployment_admin_app: FastAPI,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=demo_deployment_admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == OPS_STATUS_FIELDS
    assert body["demo_deployment_mode"] is True
    assert ADMIN_TOKEN not in response.text
    assert "postgresql" not in response.text.lower()
    await demo_deployment_admin_app.state.database.dispose()


@pytest.mark.asyncio
async def test_ops_status_reports_default_demo_deployment_mode_without_sensitive_configuration(
    default_admin_ops_app: FastAPI,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=default_admin_ops_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})

    assert response.status_code == 200
    body = response.json()
    assert body["demo_deployment_mode"] is False
    assert ADMIN_TOKEN not in response.text
    assert "postgresql" not in response.text.lower()
    await default_admin_ops_app.state.database.dispose()


@pytest.mark.asyncio
async def test_ops_status_reports_three_level_budget_cost_and_cache_without_leaks(
    admin_app: FastAPI,
) -> None:
    """三级余量、当日成本、未定价调用数与缓存命中率；店铺级只给脱敏标识（N5 B Task 3）。"""

    from datetime import UTC, datetime
    from uuid import UUID

    from app.analytics.dates import business_today

    shop = UUID("00000000-0000-0000-0000-0000000000a1")
    today = business_today(datetime.now(UTC), timezone=admin_app.state.settings.business_timezone)
    database = admin_app.state.database
    async with database.session() as session:
        for scope, used in (
            ("GLOBAL", 1_200),
            ("ROLE:MERCHANT", 1_000),
            ("ROLE:CUSTOMER", 200),
            (f"SHOP:MERCHANT:{shop}", 1_000),
        ):
            await session.execute(
                text(
                    "INSERT INTO llm_daily_budget (id, usage_date, scope_key, consumed_tokens, "
                    "call_count) VALUES (gen_random_uuid(), :d, :k, :u, 1)"
                ),
                {"d": today, "k": scope, "u": used},
            )
        for cost, hits, inputs in (("0.25", 300, 1_000), ("0.50", 100, 1_000), (None, None, 0)):
            await session.execute(
                text(
                    "INSERT INTO llm_usage (id, request_id, usage_date, model, input_tokens, "
                    "status, cost, cost_currency, cache_hit_tokens) VALUES (gen_random_uuid(), "
                    "'r', :d, 'deepseek-flash', :i, 'SUCCEEDED', :c, :cur, :h)"
                ),
                {
                    "d": today,
                    "i": inputs,
                    "c": cost,
                    "cur": "USD" if cost else None,
                    "h": hits,
                },
            )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})

    assert response.status_code == 200
    body = response.json()
    levels = {row["scope"]: row for row in body["budget_levels"]}
    assert levels["GLOBAL"]["used_tokens"] == 1_200
    assert levels["GLOBAL"]["remaining_tokens"] == 5_000 - 1_200
    assert levels["ROLE:CUSTOMER"]["level"] == "ROLE"
    (shop_scope,) = [key for key in levels if key.startswith("SHOP:")]
    assert shop_scope.startswith("SHOP:MERCHANT:") and len(shop_scope.split(":")[-1]) == 8
    assert str(shop) not in response.text
    assert body["llm_cost_today"] == [{"currency": "USD", "amount": "0.75000000"}]
    assert body["unpriced_calls_today"] == 1
    assert body["cache_hit_tokens_today"] == 400
    assert body["cache_hit_rate_today"] == pytest.approx(0.2)
    assert ADMIN_TOKEN not in response.text


@pytest.mark.asyncio
async def test_ops_status_reports_per_turn_tokens_cost_latency_and_degradation_reasons(
    admin_app: FastAPI,
) -> None:
    """每回合 token、成本、耗时与降级原因（验收 §12.6）；只有计数与平均值，不含正文与标识。"""

    from datetime import UTC, datetime
    from uuid import UUID, uuid4

    from app.analytics.dates import business_today
    from app.models.answer import Answer
    from app.models.conversation import Conversation
    from app.models.merchant import Merchant

    shop = UUID("00000000-0000-0000-0000-0000000000b2")
    today = business_today(datetime.now(UTC), timezone=admin_app.state.settings.business_timezone)
    database = admin_app.state.database
    async with database.session() as session:
        # 两个回合共三次 AGENT 调用（一个回合调了两次模型），外加一次不算回合的记忆抽取。
        for request_id, purpose, tokens, cost in (
            ("turn-a", "AGENT", 600, "0.30"),
            ("turn-a", "AGENT", 400, "0.20"),
            ("turn-b", "AGENT", 1_000, "0.10"),
            ("memory:job-1", "MEMORY", 5_000, "9.00"),
        ):
            await session.execute(
                text(
                    "INSERT INTO llm_usage (id, request_id, usage_date, model, total_tokens, "
                    "status, purpose, cost, cost_currency) VALUES (gen_random_uuid(), :r, :d, "
                    "'deepseek-flash', :t, 'SUCCEEDED', :p, :c, 'USD')"
                ),
                {"r": request_id, "d": today, "t": tokens, "p": purpose, "c": cost},
            )
        session.add(Merchant(id=shop, merchant_code="ops-turns", display_name="回合统计店"))
        await session.flush()
        conversation = Conversation(merchant_id=shop, surface="MERCHANT")
        session.add(conversation)
        await session.flush()
        for elapsed in (1_000, 3_000):
            session.add(
                Answer(
                    merchant_id=shop,
                    conversation_id=conversation.id,
                    client_request_id=f"ops-{uuid4()}",
                    request_digest="digest",
                    processing_status="SUCCEEDED",
                    response_payload={"answer": "回答正文不得出现在运维响应里"},
                    response_locale="zh-CN",
                    surface="MERCHANT",
                    elapsed_ms=elapsed,
                )
            )
        await session.commit()
    metrics = admin_app.state.metrics
    metrics.record_turn(degraded=True, reason="BUDGET", degraded_sources=[])
    metrics.record_turn(degraded=False, reason=None, degraded_sources=["KNOWLEDGE"])

    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})

    assert response.status_code == 200
    body = response.json()
    assert body["turns_today"] == 2
    assert body["avg_tokens_per_turn_today"] == pytest.approx(1_000)
    assert body["avg_cost_per_turn_today"] == [{"currency": "USD", "amount": "0.30000000"}]
    assert body["avg_turn_elapsed_ms_today"] == pytest.approx(2_000)
    assert body["degraded_count"] == 1
    assert body["degraded_reason_counts"] == {"BUDGET": 1}
    assert body["source_degraded_counts"] == {"KNOWLEDGE": 1}
    for leaked in ("回答正文", str(shop), "ops-turns", "回合统计店", ADMIN_TOKEN):
        assert leaked not in response.text


@pytest.mark.asyncio
async def test_ops_status_per_turn_fields_are_null_not_zero_without_turns(
    admin_app: FastAPI,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/ops/status", headers={"X-Admin-Token": ADMIN_TOKEN})

    body = response.json()
    assert body["turns_today"] == 0
    assert body["avg_tokens_per_turn_today"] is None
    assert body["avg_cost_per_turn_today"] == []
    assert body["avg_turn_elapsed_ms_today"] is None
    assert body["degraded_reason_counts"] == {}
    assert body["source_degraded_counts"] == {}
