"""v2 回合的降级计入运维指标（PRD §10.4；验收 §12.6）。

此前只有 v1 `/api/chat` 的降级会让 `degraded_count` 增加，v2 两端的回合从不计数，
运维看板上的「降级次数」因此恒为偏低。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from app.services.quality_types import DegradeReason
from tests.conftest import MERCHANT_ONE_AUTH
from tests.support.merchant_v2 import merchant_session_headers
from tests.support.trade import SHOP

pytestmark = pytest.mark.integration

JSON = {"Accept": "application/json"}
_DEGRADED = LlmTurn(text="", tool_calls=[], stop_reason="MAX_TOKENS", tokens=10)
_FINE = LlmTurn(text="你好，有什么可以帮你？", tool_calls=[], stop_reason="END_TURN", tokens=10)


def _script(monkeypatch: pytest.MonkeyPatch, route: str, turns: list[LlmTurn]) -> None:
    fake = FakeLlmClient(turns=turns)
    monkeypatch.setattr(f"app.api.routes.v2.{route}.build_guarded_llm", lambda *a, **k: fake)


async def _post(client: AsyncClient, path: str, headers: dict[str, str], crid: str) -> Any:
    response = await client.post(
        path, json={"client_request_id": crid, "message": "你好"}, headers={**headers, **JSON}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_degraded_merchant_turn_is_counted_once_with_its_reason(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics = postgres_app.state.metrics
    _script(monkeypatch, "merchant_chat", [_DEGRADED])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _post(postgres_client, "/api/v2/merchant/chat", headers, "turn-metric-1")

    assert body["degraded"] is True
    assert metrics.degraded_count == 1
    [(reason, count)] = metrics.degraded_reason_counts.items()
    assert count == 1 and reason in {item.value for item in DegradeReason}

    # 同一 client_request_id 的重放返回第一次的结果，不再计一次。
    replay = await _post(postgres_client, "/api/v2/merchant/chat", headers, "turn-metric-1")
    assert replay["degraded"] is True
    assert metrics.degraded_count == 1


async def test_degraded_shop_turn_is_counted(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics = postgres_app.state.metrics
    _script(monkeypatch, "shop_chat", [_DEGRADED])
    created = await postgres_client.post("/api/v2/shop/sessions", json={"shop_slug": SHOP})
    headers = {"X-Session-Id": created.json()["session_id"]}

    body = await _post(postgres_client, "/api/v2/shop/chat", headers, "turn-metric-2")

    assert body["degraded"] is True
    assert metrics.degraded_count == 1
    assert sum(metrics.degraded_reason_counts.values()) == 1


async def test_normal_turn_is_not_counted_as_degraded(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics = postgres_app.state.metrics
    _script(monkeypatch, "merchant_chat", [_FINE])
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    body = await _post(postgres_client, "/api/v2/merchant/chat", headers, "turn-metric-3")

    assert body["degraded"] is False
    assert metrics.degraded_count == 0
    assert metrics.degraded_reason_counts == {}
    assert metrics.source_degraded_counts == {}
