"""SQLAlchemy Async Engine 与 Session 生命周期。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.errors import DatabaseUnavailableError

Sleep = Callable[[float], Awaitable[None]]


class DatabaseSettings(Protocol):
    database_url: str
    db_connect_max_attempts: int
    db_connect_retry_seconds: float
    db_statement_timeout_ms: int


class Database:
    """集中管理数据库连接池和 Session 生命周期。"""

    def __init__(self, settings: DatabaseSettings, *, sleep: Sleep = asyncio.sleep) -> None:
        self._settings = settings
        self._sleep = sleep
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            connect_args={"options": f"-c statement_timeout={settings.db_statement_timeout_ms}"},
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            close_resets_only=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """提供请求级 Session，并保证退出时关闭。"""

        async with self.session_factory() as session:
            yield session

    async def ping(self) -> None:
        """执行轻量数据库探针。"""

        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def connect_with_retry(self) -> None:
        """启动时有限重试数据库连接。"""

        for attempt in range(1, self._settings.db_connect_max_attempts + 1):
            try:
                await self.ping()
                return
            except (SQLAlchemyError, OSError):
                if attempt == self._settings.db_connect_max_attempts:
                    raise DatabaseUnavailableError from None
                await self._sleep(self._settings.db_connect_retry_seconds)

    async def dispose(self) -> None:
        """释放连接池。"""

        await self.engine.dispose()
