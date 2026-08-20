"""知识库后台 API 测试共享夹具。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import AppEnvironment, Settings
from app.db.session import Database
from app.main import create_app
from app.repositories.knowledge_admin import KnowledgeAdminRepository
from app.services.knowledge_admin_service import KnowledgeAdminService
from tests.postgres import TRUNCATE_ALL_TABLES

ADMIN_TOKEN = "test-only-admin-token-value"


@pytest_asyncio.fixture
async def knowledge_admin_app(migrated_postgres: str) -> AsyncIterator[FastAPI]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
        admin_token=ADMIN_TOKEN,
    )
    database = Database(settings)
    async with database.session() as session:
        await session.execute(text(TRUNCATE_ALL_TABLES))
        await session.commit()
    app = create_app(settings, database=database)
    yield app
    await database.dispose()


@pytest_asyncio.fixture
async def admin_client(knowledge_admin_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=knowledge_admin_app), base_url="http://testserver"
    ) as client:
        client.headers["X-Admin-Token"] = ADMIN_TOKEN
        yield client


@pytest_asyncio.fixture
async def existing_document(knowledge_admin_app: FastAPI) -> str:
    path = "index/已有文档.md"
    async with knowledge_admin_app.state.database.session() as session:
        await KnowledgeAdminRepository(session).create(
            virtual_path=path,
            category="UNKNOWN",
            title="已有文档",
            content="原内容",
        )
        await session.commit()
    return path


@pytest_asyncio.fixture
async def domain_with_document(knowledge_admin_app: FastAPI) -> dict[str, str]:
    async with knowledge_admin_app.state.database.session() as session:
        repository = KnowledgeAdminRepository(session)
        document = await repository.create(
            virtual_path="业务/旧域/业务流程/a.md",
            category="TRADE",
            title="a",
            content="内容",
        )
        await session.flush()
        await session.commit()

    async with knowledge_admin_app.state.database.session() as session:
        tree = await KnowledgeAdminService(session).tree()
    business = next(root for root in tree.roots if root.path == "业务")
    domain = business.children[0]
    return {"name": document.source_path.split("/")[1], "version": domain.version}
