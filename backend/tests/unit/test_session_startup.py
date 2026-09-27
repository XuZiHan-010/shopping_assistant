"""启动身份对账必须先于服务开放，失败路径释放连接池。"""

from unittest.mock import AsyncMock

import pytest

from app.core.errors import DatabaseUnavailableError
from app.main import create_app


@pytest.mark.asyncio
async def test_connection_failure_aborts_startup_and_recovery_reconciles(
    test_settings, monkeypatch
) -> None:
    database = AsyncMock()
    database.connect_with_retry.side_effect = [DatabaseUnavailableError(), None]
    reconcile = AsyncMock(return_value=0)
    monkeypatch.setattr("app.main.reconcile_demo_issuers", reconcile)
    monkeypatch.setattr("app.main.seed_wiki_documents", AsyncMock(return_value=0))
    app = create_app(test_settings, database=database)
    with pytest.raises(DatabaseUnavailableError):
        async with app.router.lifespan_context(app):
            pytest.fail("数据库连接失败时不得开放请求")
    database.dispose.assert_awaited_once()
    reconcile.assert_not_awaited()
    async with app.router.lifespan_context(app):
        reconcile.assert_awaited_once_with(database, test_settings)
    assert database.dispose.await_count == 2


@pytest.mark.asyncio
async def test_reconciliation_failure_disposes_database(test_settings, monkeypatch) -> None:
    database = AsyncMock()
    monkeypatch.setattr(
        "app.main.reconcile_demo_issuers", AsyncMock(side_effect=RuntimeError("reconcile"))
    )
    app = create_app(test_settings, database=database)
    with pytest.raises(RuntimeError, match="reconcile"):
        async with app.router.lifespan_context(app):
            pytest.fail("身份对账失败时不得开放请求")
    database.dispose.assert_awaited_once()
