"""每日经营日报的 HTTP 契约、商家隔离与反馈复用。"""

from __future__ import annotations

import asyncio
import re

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


async def test_daily_report_renders_english_metric_labels_and_suggestions(
    postgres_client: AsyncClient,
) -> None:
    """Task 8：物化的日报永远以 zh-CN 落库（同一份 `answer_id`），展示名/单位/
    建议按请求语言经 `app.localization.catalog` 渲染——都是闭集固定文案,零
    LLM。"""

    zh_response = await postgres_client.get("/api/reports/daily", headers=MERCHANT_ONE_AUTH)
    en_response = await postgres_client.get(
        "/api/reports/daily",
        headers={**MERCHANT_ONE_AUTH, "Accept-Language": "en-US"},
    )

    assert zh_response.status_code == 200, zh_response.text
    assert en_response.status_code == 200, en_response.text
    # 同一份物化结果，只是渲染语言不同——answer_id 必须一致。
    assert zh_response.json()["answer_id"] == en_response.json()["answer_id"]

    zh_metrics = {item["metric_code"]: item for item in zh_response.json()["metrics"]}
    en_metrics = {item["metric_code"]: item for item in en_response.json()["metrics"]}
    assert zh_metrics["gmv"]["display_name"] == "成交 GMV"
    assert en_metrics["gmv"]["display_name"] == "Transaction GMV"
    assert zh_metrics["gmv"]["unit"] == "元"
    assert en_metrics["gmv"]["unit"] == "yuan"
    assert zh_metrics["gmv"]["value"] == en_metrics["gmv"]["value"]

    han_pattern = re.compile(r"[一-鿿]")
    for suggestion in en_response.json()["suggestions"]:
        assert not han_pattern.search(suggestion)


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
