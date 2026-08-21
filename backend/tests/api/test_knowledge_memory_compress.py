"""管理员手动记忆压缩端点。

对应参考项目 `POST /api/wiki/compress`：自动沉淀之外的人工兜底，让维护者能指定
商家与分类、补一段人工 Markdown 后重新压缩该商家的记忆。参考实现没有鉴权体系，
我们放进 `/api/admin/knowledge/*` 并要求 `X-Admin-Token`；这是管理员跨商家写入，
必须留审计（R5）。全程 Fake LLM，不产生任何费用（R3）。
"""

from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.models.knowledge import MerchantMemory
from app.models.merchant import Merchant
from app.models.operations import AuditLog
from app.prompts.memory import MEMORY_MARKER

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000041")
COMPRESS_PATH = "/api/admin/knowledge/memories/compress"


@pytest_asyncio.fixture
async def merchant(knowledge_admin_app: FastAPI) -> UUID:
    async with knowledge_admin_app.state.database.session() as session:
        session.add(
            Merchant(
                id=MERCHANT_ID,
                merchant_code="memory-compress-merchant",
                display_name="手动压缩商家",
            )
        )
        await session.commit()
    return MERCHANT_ID


@pytest.mark.asyncio
async def test_compress_overwrites_memory_for_requested_merchant_and_category(
    admin_client: AsyncClient,
    knowledge_admin_app: FastAPI,
    merchant: UUID,
) -> None:
    response = await admin_client.post(
        COMPRESS_PATH,
        json={
            "merchant_id": str(merchant),
            "category": "TRADE",
            "manual_markdown": "人工补充：大促期间退款口径按申请日计。",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"] == str(merchant)
    assert body["category"] == "TRADE"

    async with knowledge_admin_app.state.database.session() as session:
        memory = (
            await session.execute(
                select(MerchantMemory).where(
                    MerchantMemory.merchant_id == merchant,
                    MerchantMemory.category == "TRADE",
                )
            )
        ).scalar_one()
    assert MEMORY_MARKER in memory.content
    assert "大促期间退款口径按申请日计" in memory.content


@pytest.mark.asyncio
async def test_compress_writes_audit_log(
    admin_client: AsyncClient,
    knowledge_admin_app: FastAPI,
    merchant: UUID,
) -> None:
    await admin_client.post(
        COMPRESS_PATH,
        json={
            "merchant_id": str(merchant),
            "category": "TRADE",
            "manual_markdown": "人工补充",
        },
    )

    async with knowledge_admin_app.state.database.session() as session:
        logs = list((await session.execute(select(AuditLog))).scalars())

    assert len(logs) == 1
    assert logs[0].event_type == "ADMIN_MEMORY_COMPRESS"
    assert logs[0].merchant_id == merchant
    assert logs[0].resource_id == "TRADE"


@pytest.mark.asyncio
async def test_compress_rejects_request_without_admin_token(
    knowledge_admin_app: FastAPI,
    merchant: UUID,
) -> None:
    from httpx import ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=knowledge_admin_app), base_url="http://testserver"
    ) as anonymous:
        response = await anonymous.post(
            COMPRESS_PATH,
            json={
                "merchant_id": str(merchant),
                "category": "TRADE",
                "manual_markdown": "人工补充",
            },
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_compress_rejects_unknown_merchant(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        COMPRESS_PATH,
        json={
            "merchant_id": "00000000-0000-0000-0000-0000000000ff",
            "category": "TRADE",
            "manual_markdown": "人工补充",
        },
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_compress_reports_degraded_when_model_unavailable(
    admin_client: AsyncClient,
    merchant: UUID,
) -> None:
    """测试环境未配置模型，压缩必须如实暴露确定性兜底（R7）。"""

    response = await admin_client.post(
        COMPRESS_PATH,
        json={"merchant_id": str(merchant), "category": "TRADE", "manual_markdown": "人工补充"},
    )

    body = response.json()
    assert body["degraded"] is True
    assert body["degraded_reason"]


@pytest.mark.asyncio
async def test_compress_rejects_unknown_category(
    admin_client: AsyncClient,
    merchant: UUID,
) -> None:
    response = await admin_client.post(
        COMPRESS_PATH,
        json={"merchant_id": str(merchant), "category": "TRDAE", "manual_markdown": "人工补充"},
    )

    assert response.status_code == 422
