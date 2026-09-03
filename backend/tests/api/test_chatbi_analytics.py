"""Chat BI 管理员端点的鉴权与 HTTP 契约。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.analytics.chatbi_metrics import QaCounters
from app.core.config import AppEnvironment, Settings
from app.main import create_app
from app.repositories.chatbi import DailyRow
from app.schemas.chat import CATEGORY_DISPLAY_NAMES, QuestionCategory
from tests.conftest import MERCHANT_ONE_TOKEN

ADMIN_TOKEN = "test-only-admin-token-value"
OVERVIEW = "/api/admin/analytics/chatbi/overview"
CATEGORIES = "/api/admin/analytics/chatbi/categories"
ROLLUP = "/api/admin/analytics/chatbi/rollup"
WINDOW = {"start_date": "2026-08-17", "end_date": "2026-08-23"}


def _counters() -> QaCounters:
    return QaCounters(
        answer_total=4,
        adopted_count=2,
        like_count=1,
        dislike_count=1,
        first_pass_count=3,
        business_question_total=3,
        hit_count=2,
        degraded_count=1,
        thinking_sample_count=4,
        thinking_ms_sum=4000,
    )


class FakeChatBiRepository:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def load_daily(self, *, start_date: date, end_date: date) -> list[DailyRow]:
        row = DailyRow(date(2026, 8, 20), uuid4(), "TRADE", _counters())
        return [row] if start_date <= row.stat_date <= end_date else []

    async def rollup_range(self, *, start_date: date, end_date: date) -> int:
        del start_date, end_date
        return 1


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"X-Admin-Token": ADMIN_TOKEN}


@pytest_asyncio.fixture
async def admin_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
    )
    monkeypatch.setattr("app.api.routes.analytics.ChatBiRepository", FakeChatBiRepository)
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_overview_requires_admin_token(admin_client: AsyncClient) -> None:
    assert (await admin_client.get(OVERVIEW, params=WINDOW)).status_code == 401


@pytest.mark.asyncio
async def test_chatbi_routes_are_absent_without_configured_admin_token() -> None:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
    )
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(OVERVIEW, params=WINDOW)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_overview_rejects_invalid_admin_token(
    admin_client: AsyncClient,
) -> None:
    response = await admin_client.get(
        OVERVIEW, params=WINDOW, headers={"X-Admin-Token": "not-the-admin-token"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_overview_rejects_merchant_authorization_header(admin_client: AsyncClient) -> None:
    response = await admin_client.get(
        OVERVIEW, params=WINDOW, headers={"Authorization": f"Bearer {MERCHANT_ONE_TOKEN}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_overview_returns_flat_six_metrics(
    admin_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await admin_client.get(OVERVIEW, params=WINDOW, headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert {
        "adoption_rate",
        "user_accuracy_rate",
        "system_accuracy_rate",
        "avg_thinking_ms",
        "hit_rate",
        "failure_rate",
    } <= set(payload)
    assert payload["daily"][0]["adoption_rate"] == pytest.approx(0.5)
    assert payload["answer_total"] == 4


@pytest.mark.asyncio
async def test_overview_rejects_invalid_windows(
    admin_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    reversed_response = await admin_client.get(
        OVERVIEW,
        params={"start_date": "2026-08-23", "end_date": "2026-08-17"},
        headers=admin_headers,
    )
    oversized_response = await admin_client.get(
        OVERVIEW,
        params={"start_date": "2025-08-23", "end_date": "2026-08-23"},
        headers=admin_headers,
    )

    assert reversed_response.status_code == 422
    assert oversized_response.status_code == 422


@pytest.mark.asyncio
async def test_categories_require_admin_token(admin_client: AsyncClient) -> None:
    assert (await admin_client.get(CATEGORIES, params=WINDOW)).status_code == 401


@pytest.mark.asyncio
async def test_categories_return_wrapped_items_with_display_name(
    admin_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await admin_client.get(CATEGORIES, params=WINDOW, headers=admin_headers)

    assert response.status_code == 200
    assert (
        response.json()["items"][0]["category_display_name"]
        == CATEGORY_DISPLAY_NAMES[QuestionCategory.TRADE]
    )


@pytest.mark.asyncio
async def test_categories_return_english_display_name_with_accept_language_header(
    admin_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Task 8：分类展示名走 `localize_catalog_value()`（零 LLM，词典已在 Task 4
    登记）。`FakeChatBiRepository` 是内存假实现，本用例结构上不可能触发任何
    真实模型调用。"""

    response = await admin_client.get(
        CATEGORIES,
        params=WINDOW,
        headers={**admin_headers, "Accept-Language": "en-US"},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["category_display_name"] == "E-commerce trade"
    assert response.json()["items"][0]["category"] == "TRADE"


@pytest.mark.asyncio
async def test_rollup_requires_admin_token(admin_client: AsyncClient) -> None:
    assert (await admin_client.post(ROLLUP, json=WINDOW)).status_code == 401


@pytest.mark.asyncio
async def test_rollup_accepts_window_body_and_returns_window(
    admin_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await admin_client.post(ROLLUP, json=WINDOW, headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {**WINDOW, "rows_written": 1}


@pytest.mark.asyncio
async def test_overview_response_contains_no_merchant_identifiers(
    admin_client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await admin_client.get(OVERVIEW, params=WINDOW, headers=admin_headers)
    assert "merchant_id" not in response.text
    assert '"question":' not in response.text
