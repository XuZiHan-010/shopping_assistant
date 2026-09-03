"""目录树：三个根、固定板块顺序、memory 只读。"""

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
from tests.postgres import TRUNCATE_ALL_TABLES

ADMIN_TOKEN = "test-only-admin-token-value"


@pytest_asyncio.fixture
async def admin_app(migrated_postgres: str) -> AsyncIterator[FastAPI]:
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
async def admin_client(admin_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        client.headers["X-Admin-Token"] = ADMIN_TOKEN
        yield client


@pytest_asyncio.fixture
async def seeded_domain(admin_app: FastAPI) -> None:
    async with admin_app.state.database.session() as session:
        repository = KnowledgeAdminRepository(session)
        await repository.create(
            virtual_path="业务/交易/业务流程/下单.md",
            category="TRADE",
            title="下单",
            content="流程说明",
        )
        await session.commit()


async def test_tree_returns_three_roots_in_fixed_order(admin_client: AsyncClient) -> None:
    response = await admin_client.get("/api/admin/knowledge/tree")

    assert response.status_code == 200
    roots = response.json()["roots"]
    assert [root["path"] for root in roots] == ["index", "业务", "memory"]


async def test_memory_root_is_read_only(admin_client: AsyncClient) -> None:
    roots = (await admin_client.get("/api/admin/knowledge/tree")).json()["roots"]
    memory = next(root for root in roots if root["path"] == "memory")

    assert memory["read_only"] is True


async def test_business_sections_follow_reference_order(
    admin_client: AsyncClient, seeded_domain: None
) -> None:
    roots = (await admin_client.get("/api/admin/knowledge/tree")).json()["roots"]
    business = next(root for root in roots if root["path"] == "业务")
    domain = business["children"][0]

    assert [child["name"] for child in domain["children"]] == [
        "业务流程",
        "业务名词解释",
        "ddl",
        "指标或调用指标平台mcp的skill",
    ]


async def test_tree_requires_admin_token(admin_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/admin/knowledge/tree")

    assert response.status_code == 401


async def test_merchant_token_is_rejected(admin_app: FastAPI) -> None:
    """管理员令牌不复用 Authorization——商家 Token 调管理接口必须失败。"""

    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/api/admin/knowledge/tree",
            headers={"Authorization": "Bearer merchant-one-token"},
        )

    assert response.status_code == 401


async def test_tree_localizes_fixed_section_names_but_keeps_path_unchanged(
    admin_client: AsyncClient, seeded_domain: None
) -> None:
    """Task 8：树节点只本地化 `name`（固定导航标签），`path` 是 API 定位
    文档用的真实标识符，绝不随语言变化。用户创建的业务域名称（"交易"）不在
    闭集词典里，原样保留——不因为翻译不到就报错或留白。"""

    response = await admin_client.get(
        "/api/admin/knowledge/tree", params={"content_locale": "en-US"}
    )

    assert response.status_code == 200
    roots = response.json()["roots"]
    business = next(root for root in roots if root["path"] == "业务")
    assert business["name"] == "Business"
    domain = business["children"][0]
    assert domain["path"] == "业务/交易"
    assert domain["name"] == "交易"  # 用户创建的业务域名称：不在词典里，原样保留
    section_names = {child["path"]: child["name"] for child in domain["children"]}
    assert section_names["业务/交易/业务流程"] == "Business process"
    assert section_names["业务/交易/业务名词解释"] == "Business glossary"
    assert section_names["业务/交易/ddl"] == "ddl"  # 无汉字，原样保留


async def test_tree_without_content_locale_keeps_chinese_names_unchanged(
    admin_client: AsyncClient, seeded_domain: None
) -> None:
    """缺省 `content_locale` 时行为与本字段引入前完全一致（向后兼容）。"""

    response = await admin_client.get("/api/admin/knowledge/tree")

    assert response.status_code == 200
    business = next(root for root in response.json()["roots"] if root["path"] == "业务")
    assert business["name"] == "业务"
