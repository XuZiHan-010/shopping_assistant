"""W Task 2：`GET /api/v2/merchant/metrics/overview`（契约 §8.12.4），真实 PostgreSQL。

首页主指标的每个数字都必须与商家助手的 `query_metrics` / `attribute_change`
工具在同一时刻给出的结果一致——两处复用同一个 `AttributionService`，不另写口径。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update

import app.tools.merchant.metrics as metrics_tools
from app.api.routes.v2.merchant_insights import get_overview_now
from app.core.session import SessionContext, SessionRole
from app.db.session import Database
from app.models.analytics import OrderItem, Product, Refund
from app.models.operations import AuditLog
from app.tools.merchant.metrics import AttributeChangeArgs, QueryMetricsArgs, build_metrics_tools
from app.tools.types import ToolContext
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product

pytestmark = pytest.mark.integration

OVERVIEW_PATH = "/api/v2/merchant/metrics/overview"
TZ = "Asia/Shanghai"
# 周三 04:00 UTC = 上海 12:00：日内时刻，工具与本端点逐项比对。
FROZEN_NOW = datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
# 周日 20:00 UTC = 上海周一 04:00：UTC 日期比业务日期早一天，且跨周。
CROSS_DAY_NOW = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)


def _frozen_datetime(frozen: datetime) -> type[datetime]:
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def, override]
            return frozen if tz is None else frozen.astimezone(tz)

    return _FrozenDatetime


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


async def _set_category(database: Database, product_id: UUID, category: str) -> None:
    async with database.session() as session:
        await session.execute(
            update(Product).where(Product.id == product_id).values(category=category)
        )
        await session.commit()


async def _refund(database: Database, order_id: UUID, amount: str, *, day: date) -> None:
    async with database.session() as session:
        item = await session.scalar(select(OrderItem).where(OrderItem.order_id == order_id))
        assert item is not None
        session.add(
            Refund(
                merchant_id=item.merchant_id,
                business_date=day,
                order_item_id=item.id,
                refund_amount=Decimal(amount),
                refund_reason="测试退款",
                refund_status="REFUNDED",
                refunded_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            )
        )
        await session.commit()


async def _seed(database: Database) -> None:
    """本期（9/21–9/23）茶饮 300−30、烘焙 100；基期（9/14–9/16）茶饮 200、烘焙 100。"""

    tea = await seed_product(database, MERCHANT_ONE_ID, title="茶饮商品", now=FROZEN_NOW)
    bakery = await seed_product(database, MERCHANT_ONE_ID, title="烘焙商品", now=FROZEN_NOW)
    await _set_category(database, tea, "茶饮")
    await _set_category(database, bakery, "烘焙")
    tea_now = await seed_paid_order(
        database, MERCHANT_ONE_ID, tea, quantity=3, days_ago=1, now=FROZEN_NOW
    )
    await seed_paid_order(database, MERCHANT_ONE_ID, bakery, quantity=1, days_ago=2, now=FROZEN_NOW)
    await seed_paid_order(database, MERCHANT_ONE_ID, tea, quantity=2, days_ago=8, now=FROZEN_NOW)
    await seed_paid_order(database, MERCHANT_ONE_ID, bakery, quantity=1, days_ago=9, now=FROZEN_NOW)
    await _refund(database, tea_now, "30.00", day=date(2026, 9, 22))

    # 他店的大额订单：不得进入本店任何数字（R5）。
    other = await seed_product(database, MERCHANT_TWO_ID, title="他店商品", now=FROZEN_NOW)
    await seed_paid_order(database, MERCHANT_TWO_ID, other, quantity=50, days_ago=1, now=FROZEN_NOW)


def _forbid_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """任何 LLM 客户端被构造即失败：真实、脚本化替身与费用守卫一并封死。"""

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("指标总览不得构造或调用任何 LLM 客户端")

    monkeypatch.setattr("app.llm.deepseek.DeepSeekLlmClient.__init__", forbidden)
    monkeypatch.setattr("app.llm.fake.FakeLlmClient.__init__", forbidden)
    monkeypatch.setattr("app.llm.guard.LlmCostGuard.__init__", forbidden)
    monkeypatch.setattr("app.api.dependencies.build_guarded_llm", forbidden)


async def _get_overview(
    app: FastAPI,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime = FROZEN_NOW,
    **headers: str,
) -> Any:
    _forbid_llm(monkeypatch)
    app.dependency_overrides[get_overview_now] = lambda: now
    session_headers = await merchant_session_headers(client, MERCHANT_ONE_AUTH)
    resp = await client.get(OVERVIEW_PATH, headers={**session_headers, **headers})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _tool_ctx() -> ToolContext:
    return ToolContext(
        session=SessionContext(
            session_record_id=UUID("00000000-0000-0000-0000-00000000c0a1"),
            role=SessionRole.MERCHANT,
            merchant_id=MERCHANT_ONE_ID,
            buyer_key=None,
            shop_slug=None,
        ),
        conversation_id="conv-overview",
        request_id="req-overview",
    )


def _cents(value: str | None) -> int | None:
    return None if value is None else int(Decimal(value) * 100)


def _bp(value: str | None) -> int | None:
    return None if value is None else int(Decimal(value) * 10000)


@pytest.mark.asyncio
async def test_overview_matches_query_metrics_and_attribute_change_tools(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    await _seed(database)

    body = await _get_overview(postgres_app, postgres_client, monkeypatch)

    monkeypatch.setattr(metrics_tools, "datetime", _frozen_datetime(FROZEN_NOW))
    tools = {spec.name: spec for spec in build_metrics_tools(database, business_timezone=TZ)}
    ctx = _tool_ctx()

    async def tool_value(metric: str, period: dict[str, str]) -> str | None:
        output = await tools["query_metrics"].executor(
            ctx,
            QueryMetricsArgs(
                metric=metric,
                start=date.fromisoformat(period["start"]),
                end=date.fromisoformat(period["end"]),
            ),
        )
        return output.payload["value"]  # type: ignore[no-any-return]

    current, baseline = body["current_period"], body["baseline_period"]
    assert (current["start"], current["end"]) == ("2026-09-21", "2026-09-23")
    assert (baseline["start"], baseline["end"]) == ("2026-09-14", "2026-09-16")

    headline = body["headline"]
    assert headline["current_cents"] == _cents(await tool_value("net_gmv", current)) == 37000
    assert headline["baseline_cents"] == _cents(await tool_value("net_gmv", baseline)) == 30000
    assert headline["change_ratio_bp"] == 2333
    assert [p["value_cents"] for p in headline["current_series"]] == [10000, 27000, 0]

    attribution_output = await tools["attribute_change"].executor(
        ctx, AttributeChangeArgs(metric="net_gmv", dimension="category")
    )
    expected = attribution_output.payload
    assert expected["stopped"] is False
    assert body["attribution"]["mode"] == expected["mode"] == "SHARE"
    assert [
        (s["name"], s["current_cents"], s["baseline_cents"], s["contribution_cents"], s["share_bp"])
        for s in body["attribution"]["segments"]
    ] == [
        (
            s["name"],
            _cents(s["current_value"]),
            _cents(s["baseline_value"]),
            _cents(s["absolute_contribution"]),
            _bp(s["share"]),
        )
        for s in expected["segments"]
    ]
    assert [s["name"] for s in body["attribution"]["segments"]] == ["茶饮", "烘焙"]
    assert body["attribution"]["remaining_count"] == 0

    secondary = {item["metric_code"]: item for item in body["secondary"]}
    assert [item["metric_code"] for item in body["secondary"]] == [
        "order_count",
        "refund_amount",
        "return_rate",
    ]
    for period_key, field in (("current", "current_value"), ("baseline", "baseline_value")):
        period = current if period_key == "current" else baseline
        order_count = await tool_value("order_count", period)
        refund_amount = await tool_value("refund_amount", period)
        return_rate = await tool_value("return_rate", period)
        assert secondary["order_count"][field] == (
            None if order_count is None else int(Decimal(order_count))
        )
        assert secondary["refund_amount"][field] == _cents(refund_amount)
        assert secondary["return_rate"][field] == _bp(return_rate)
    assert secondary["order_count"]["current_value"] == 2
    assert secondary["refund_amount"]["current_value"] == 3000
    assert secondary["refund_amount"]["baseline_value"] is None


@pytest.mark.asyncio
async def test_attribute_change_tool_uses_business_day_across_utc_midnight(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上海 00:00–08:00 时 UTC 仍是前一天：工具必须与首页同按业务日取「今天」。

    冻结在上海周一 04:00（UTC 周日 20:00）：业务上本周只有周一 1 天，
    按 UTC 取日期则会落到上一整周，周期、标签与数字都与首页对不上。
    """

    database = _database(postgres_app)
    await _seed(database)

    body = await _get_overview(postgres_app, postgres_client, monkeypatch, now=CROSS_DAY_NOW)
    assert (body["current_period"]["start"], body["current_period"]["end"]) == (
        "2026-09-28",
        "2026-09-28",
    )

    monkeypatch.setattr(metrics_tools, "datetime", _frozen_datetime(CROSS_DAY_NOW))
    tools = {spec.name: spec for spec in build_metrics_tools(database, business_timezone=TZ)}
    output = await tools["attribute_change"].executor(
        _tool_ctx(), AttributeChangeArgs(metric="net_gmv", dimension="category")
    )

    assert output.payload["data_cutoff"] == "2026-09-28"
    assert output.payload["comparison"] == [
        body["current_period"]["label"],
        body["baseline_period"]["label"],
    ]
    assert [(s["name"], _cents(s["baseline_value"])) for s in output.payload["segments"]] == [
        (s["name"], s["baseline_cents"]) for s in body["attribution"]["segments"]
    ]


@pytest.mark.asyncio
async def test_overview_discloses_database_source_and_no_reviewer(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(_database(postgres_app))

    body = await _get_overview(postgres_app, postgres_client, monkeypatch)

    assert body["analysis_sources"] == [
        {"source": "DATABASE", "degraded": False, "degraded_reason": None}
    ]
    assert body["quality_status"] == "NOT_RUN"
    assert body["quality_attempts"] == 0
    assert body["quality_notes"] == []
    assert body["degraded"] is False
    assert body["degraded_reason"] is None
    assert body["business_timezone"] == TZ
    assert body["source"] == "REALTIME"
    assert body["definition_version"]
    assert datetime.fromisoformat(body["data_as_of"]) == FROZEN_NOW
    assert "buyer_key" not in str(body)


@pytest.mark.asyncio
async def test_overview_labels_follow_accept_language(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(_database(postgres_app))

    body = await _get_overview(
        postgres_app, postgres_client, monkeypatch, **{"Accept-Language": "en-US"}
    )

    assert body["current_period"]["label"] == "First 3 days this week"
    assert body["baseline_period"]["label"] == "First 3 days last week"


@pytest.mark.asyncio
async def test_new_merchant_without_baseline_is_not_degraded(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, now=FROZEN_NOW)
    await seed_paid_order(
        database, MERCHANT_ONE_ID, product, quantity=1, days_ago=1, now=FROZEN_NOW
    )

    body = await _get_overview(postgres_app, postgres_client, monkeypatch)

    assert body["headline"]["current_cents"] == 10000
    assert body["headline"]["baseline_cents"] is None
    assert body["headline"]["baseline_series"] == []
    assert body["attribution"]["mode"] == "STOPPED"
    assert body["attribution"]["stopped_reason"]
    assert body["degraded"] is False


@pytest.mark.asyncio
async def test_overview_requires_a_merchant_session(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    missing = await postgres_client.get(OVERVIEW_PATH)
    assert missing.status_code == 401

    created = await postgres_client.post(
        "/api/v2/shop/sessions", json={"shop_slug": "borough-api-100"}
    )
    customer = await postgres_client.get(
        OVERVIEW_PATH, headers={"X-Session-Id": created.json()["session_id"]}
    )
    assert customer.status_code == 403
    assert customer.json()["code"] == "SESSION_ROLE_MISMATCH"
    async with _database(postgres_app).session() as session:
        events = (
            await session.scalars(
                select(AuditLog.event_type).where(AuditLog.event_type == "SESSION_ROLE_MISMATCH")
            )
        ).all()
    assert events


@pytest.mark.asyncio
async def test_overview_rejects_date_parameters_by_ignoring_them(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """周期由后端固定：前端传来的日期参数不改变周期。"""

    await _seed(_database(postgres_app))
    _forbid_llm(monkeypatch)
    postgres_app.dependency_overrides[get_overview_now] = lambda: FROZEN_NOW
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    resp = await postgres_client.get(
        OVERVIEW_PATH,
        headers=headers,
        params={"start": "2026-01-01", "end": "2026-01-07", "merchant_id": str(MERCHANT_TWO_ID)},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["current_period"]["start"] == "2026-09-21"
    assert resp.json()["headline"]["current_cents"] == 37000

