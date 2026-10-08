"""只读令牌读商家记忆时不得触发机器翻译（R3、R6）。

`GET /api/admin/knowledge/documents/{path}` 两把钥匙都认，但记忆节点在请求语言与
源语言不一致时会走一次按商家计费的机器翻译。只读令牌可以打包进前端构建产物、等同
公开，所以它只能读已有的译文缓存，永远不能自己发起模型调用；否则任何人都能拿公开
令牌烧商家预算，「只读令牌泄露的最坏后果只是看到只读内容」这句话就不成立了。

全程 Fake LLM，不产生任何费用。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import knowledge as knowledge_routes
from app.core.config import AppEnvironment, Settings
from app.db.session import Database
from app.llm.fake import FakeLlmClient
from app.llm.guard import LlmCostGuard
from app.main import create_app
from app.models.knowledge import MerchantMemory
from app.models.merchant import Merchant
from app.repositories.llm_budget import LlmBudgetRepository
from tests.postgres import truncate_all_tables

ADMIN_TOKEN = "test-only-admin-token-value"
VIEWER_TOKEN = "test-only-viewer-token-value"
MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000042")
MEMORY_PATH = f"/api/admin/knowledge/documents/memory/merchants/{MERCHANT_ID}/TRADE.md"
SOURCE_TEXT = "大促期间退款口径按申请日计。"
TRANSLATED_TEXT = "Refunds during promotions are counted by request date."


@pytest_asyncio.fixture
async def app_with_memory(migrated_postgres: str) -> AsyncIterator[FastAPI]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
        viewer_token=VIEWER_TOKEN,
    )
    database = Database(settings)
    async with database.session() as session:
        await truncate_all_tables(session)
        session.add(
            Merchant(
                id=MERCHANT_ID,
                merchant_code="viewer-memory-merchant",
                display_name="只读令牌记忆商家",
            )
        )
        await session.flush()
        session.add(
            MerchantMemory(
                merchant_id=MERCHANT_ID,
                category="TRADE",
                content=SOURCE_TEXT,
                source_locale="zh-CN",
            )
        )
        await session.commit()
    app = create_app(settings, database=database)
    yield app
    await database.dispose()


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLlmClient:
    """把路由里的模型客户端换成已配置的 Fake，保留真实费用守卫与预算检查。"""

    fake = FakeLlmClient(
        responses=[json.dumps({"items": [{"key": "content", "text": TRANSLATED_TEXT}]})]
    )

    def build(settings: Settings, database: Database, **kwargs: Any) -> LlmCostGuard:
        return LlmCostGuard(fake, LlmBudgetRepository(database), settings, **kwargs)

    monkeypatch.setattr(knowledge_routes, "build_guarded_llm", build)
    return fake


async def _read_memory(app: FastAPI, token: str, locale: str) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        response = await c.get(
            MEMORY_PATH, params={"content_locale": locale}, headers={"X-Admin-Token": token}
        )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.asyncio
async def test_viewer_token_never_triggers_machine_translation(
    app_with_memory: FastAPI, fake_llm: FakeLlmClient
) -> None:
    body = await _read_memory(app_with_memory, VIEWER_TOKEN, "en-US")

    assert fake_llm.calls == []
    # 降级必须可见（R7）：原样返回源正文并标记 MISSING，不把中文原文冒充成英文译文。
    assert body["content"] == SOURCE_TEXT
    assert body["content_locale"] == "zh-CN"
    assert body["translation_status"] == "MISSING"


@pytest.mark.asyncio
async def test_admin_token_still_translates_memory(
    app_with_memory: FastAPI, fake_llm: FakeLlmClient
) -> None:
    """配对断言：同一份记忆、同一请求语言下管理员令牌确实会调用模型，
    上面「只读令牌零调用」才不是因为这条路径本来就走不通。"""

    body = await _read_memory(app_with_memory, ADMIN_TOKEN, "en-US")

    assert len(fake_llm.calls) == 1
    assert body["content"] == TRANSLATED_TEXT
    assert body["translation_status"] == "CURRENT"


@pytest.mark.asyncio
async def test_viewer_token_reads_translation_cached_by_admin(
    app_with_memory: FastAPI, fake_llm: FakeLlmClient
) -> None:
    """只读令牌不发起翻译，但管理员已经翻译过的缓存照常可读。"""

    await _read_memory(app_with_memory, ADMIN_TOKEN, "en-US")
    body = await _read_memory(app_with_memory, VIEWER_TOKEN, "en-US")

    assert len(fake_llm.calls) == 1
    assert body["content"] == TRANSLATED_TEXT
    assert body["translation_status"] == "CURRENT"
