import asyncio
import os
import sys
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from uuid import UUID

import pytest
import pytest_asyncio
from alembic import command
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppEnvironment, Settings
from app.db.session import Database
from app.main import create_app
from app.models.merchant import Merchant
from tests.postgres import (
    DEFAULT_TEST_DATABASE_URL,
    TRUNCATE_ALL_TABLES,
    alembic_config,
    assert_test_database,
    database_is_reachable,
    integration_db_is_required,
)

MERCHANT_ONE_ID = UUID("00000000-0000-0000-0000-0000000001a1")
MERCHANT_TWO_ID = UUID("00000000-0000-0000-0000-0000000001a2")
MERCHANT_ONE_TOKEN = "merchant-one-token"
MERCHANT_TWO_TOKEN = "merchant-two-token"

MERCHANT_ONE_AUTH = {"Authorization": f"Bearer {MERCHANT_ONE_TOKEN}"}
MERCHANT_TWO_AUTH = {"Authorization": f"Bearer {MERCHANT_TWO_TOKEN}"}


def pytest_asyncio_loop_factories(
    config: pytest.Config,
    item: pytest.Item,
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    """指定 pytest-asyncio 建循环的方式。

    Windows 默认的 ProactorEventLoop 跑不了 psycopg 异步模式，集成测试
    会在建立连接时直接抛 InterfaceError。这里与运行时的
    `app.core.runtime.configure_event_loop_policy` 保持同一选择。

    用 hook 而不是 `event_loop_policy` fixture：后者已被 pytest-asyncio
    标记为弃用，会在未来版本移除。
    """

    del config, item
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        app_version="0.1.0",
        database_url="postgresql+psycopg://user:pass@localhost/test",
        frontend_origin="http://localhost:5173",
        demo_merchant_tokens={},
    )


@pytest.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(test_settings)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def postgres_url() -> str:
    database_url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    assert_test_database(database_url)
    if not database_is_reachable(database_url):
        message = (
            f"真实 PostgreSQL 测试库不可用（{make_url(database_url).render_as_string()}）；"
            "请启动 Docker Desktop 并执行 docker-compose -p borough up -d postgres"
        )
        if integration_db_is_required():
            # 商家隔离、迁移和 Seed 的验收全在集成测试里。本地缺库跳过是便利，
            # CI 里跳过就是把安全地基悄悄放行——设 REQUIRE_INTEGRATION_DB=1 让它硬失败。
            pytest.fail(f"{message}（REQUIRE_INTEGRATION_DB 已开启，禁止跳过）", pytrace=False)
        pytest.skip(message)
    return database_url


@pytest.fixture(scope="session")
def migrated_postgres(postgres_url: str) -> Iterator[str]:
    config = alembic_config(postgres_url)
    command.upgrade(config, "head")
    yield postgres_url


@pytest_asyncio.fixture
async def integration_database(migrated_postgres: str) -> AsyncIterator[Database]:
    settings = Settings(
        app_env="test",
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
    )
    database = Database(settings)
    yield database
    await database.dispose()


@pytest_asyncio.fixture
async def db_session(integration_database: Database) -> AsyncIterator[AsyncSession]:
    async with integration_database.session() as session:
        await session.execute(text(TRUNCATE_ALL_TABLES))
        await session.commit()
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def merchant_one_id(db_session: AsyncSession) -> UUID:
    """经营数据表对 merchant_id 有外键约束，夹具必须先落一行商家记录。"""

    db_session.add(
        Merchant(
            id=MERCHANT_ONE_ID,
            merchant_code="borough-analytics-100",
            display_name="Borough商家100",
        )
    )
    await db_session.flush()
    return MERCHANT_ONE_ID


@pytest_asyncio.fixture
async def merchant_two_id(db_session: AsyncSession) -> UUID:
    db_session.add(
        Merchant(
            id=MERCHANT_TWO_ID,
            merchant_code="borough-analytics-101",
            display_name="Borough商家101",
        )
    )
    await db_session.flush()
    return MERCHANT_TWO_ID


@pytest_asyncio.fixture
async def postgres_app(migrated_postgres: str) -> AsyncIterator[FastAPI]:
    """接真实 PostgreSQL 的应用，用于 API 层的隔离与持久化验收。

    ASGITransport 不跑 lifespan，所以连接池由本夹具负责释放。
    """

    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url=migrated_postgres,
        frontend_origin="http://localhost:5173",
        demo_merchant_tokens={
            MERCHANT_ONE_TOKEN: MERCHANT_ONE_ID,
            MERCHANT_TWO_TOKEN: MERCHANT_TWO_ID,
        },
    )
    database = Database(settings)
    async with database.session() as session:
        await session.execute(text(TRUNCATE_ALL_TABLES))
        session.add_all(
            [
                Merchant(
                    id=MERCHANT_ONE_ID,
                    merchant_code="borough-api-100",
                    display_name="Borough商家100",
                ),
                Merchant(
                    id=MERCHANT_TWO_ID,
                    merchant_code="borough-api-101",
                    display_name="Borough商家101",
                ),
            ]
        )
        await session.commit()

    app = create_app(settings, database=database)
    yield app
    await database.dispose()


@pytest_asyncio.fixture
async def postgres_client(postgres_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=postgres_app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client
