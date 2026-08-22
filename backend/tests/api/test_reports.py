"""每日经营日报的 HTTP 契约、商家隔离与反馈复用。"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_TWO_AUTH

pytestmark = pytest.mark.asyncio


async def test_daily_report_requires_merchant_authentication(postgres_client: AsyncClient) -> None:
    response = await postgres_client.get("/api/reports/daily")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


async def test_daily_report_is_idempotent_per_merchant_and_can_be_adopted(
    postgres_client: AsyncClient,
) -> None:
    first = await postgres_client.get("/api/reports/daily", headers=MERCHANT_ONE_AUTH)
    repeated = await postgres_client.get("/api/reports/daily", headers=MERCHANT_ONE_AUTH)
    other = await postgres_client.get("/api/reports/daily", headers=MERCHANT_TWO_AUTH)

    assert first.status_code == 200, first.text
    assert repeated.status_code == 200, repeated.text
    assert other.status_code == 200, other.text
    assert first.json()["answer_id"] == repeated.json()["answer_id"]
    assert first.json()["answer_id"] != other.json()["answer_id"]
    assert [item["metric_code"] for item in first.json()["metrics"]] == [
        "gmv",
        "ordering_user_count",
        "order_count",
        "successful_order_count",
        "return_count",
        "refund_amount",
    ]
    assert len(first.json()["suggestions"]) == 2

    feedback = await postgres_client.post(
        f"/api/answers/{first.json()['answer_id']}/feedback",
        headers=MERCHANT_ONE_AUTH,
        json={"is_adopted": True, "reaction": None},
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["is_adopted"] is True


async def test_concurrent_first_daily_report_requests_return_the_same_answer(
    postgres_client: AsyncClient,
) -> None:
    first, second = await asyncio.gather(
        postgres_client.get("/api/reports/daily", headers=MERCHANT_ONE_AUTH),
        postgres_client.get("/api/reports/daily", headers=MERCHANT_ONE_AUTH),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["answer_id"] == second.json()["answer_id"]
