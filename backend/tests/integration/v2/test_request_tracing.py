"""追踪 ID 贯穿到用量记账（N5 B Task 3；PRD §10.4）。

前端生成 `X-Request-Id`，后端沿用（缺失时补生成）并写进每条 `llm_usage`；三级预算的角色与价格版本
随同一行落库。这里保留**真实的费用守卫**，只把它包着的原始模型客户端换成脚本替身，所以记账路径与生产一致。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from app.models.operations import LlmUsage
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers

pytestmark = pytest.mark.integration

TRACE = "trace-n5-b3-0001"


async def test_request_id_and_role_reach_llm_usage_rows(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted = FakeLlmClient(
        turns=[LlmTurn(text="今天一切正常。", tool_calls=[], stop_reason="END_TURN", tokens=10)]
    )
    # 只替换原始客户端（未配置 Key 时 build_guarded_llm 会构造的那一个），守卫保持真实。
    monkeypatch.setattr("app.api.dependencies.FakeLlmClient", lambda **_: scripted)
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)

    response = await postgres_client.post(
        "/api/v2/merchant/chat",
        json={"message": "今天怎么样", "client_request_id": "req-trace-0001"},
        headers={**headers, "Accept": "application/json", "X-Request-Id": TRACE},
    )

    assert response.status_code == 200, response.text
    assert response.headers["x-request-id"] == TRACE
    async with postgres_app.state.database.session() as session:
        rows = list(await session.scalars(select(LlmUsage).where(LlmUsage.request_id == TRACE)))
    assert rows, "带追踪 ID 的回合没有落用量行"
    assert {row.role for row in rows} == {"MERCHANT"}
    assert {row.merchant_id for row in rows} == {MERCHANT_ONE_ID}
