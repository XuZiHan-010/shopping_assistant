"""LlmBudgetRepository 的原子预扣在并发下不超发（§B7 必测）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.session import Database
from app.repositories.llm_budget import LlmBudgetRepository
from tests.postgres import TRUNCATE_ALL_TABLES

USAGE_DATE = date(2026, 8, 6)


@pytest_asyncio.fixture
async def clean_database(integration_database: Database) -> AsyncIterator[Database]:
    """为仓储自行管理的事务显式清理数据库。"""

    async with integration_database.session() as session:
        await session.execute(text(TRUNCATE_ALL_TABLES))
        # 通用的经营数据截断集合不含这个 B7 新表；测试必须可重复执行。
        await session.execute(text("TRUNCATE TABLE llm_daily_budget CASCADE"))
        await session.commit()
    yield integration_database


@pytest.mark.asyncio
async def test_concurrent_reserve_near_budget_never_overspends(
    clean_database: Database,
) -> None:
    """10 个并发请求逼近预算边界时，放行数精确等于预算可容纳数。"""

    repository = LlmBudgetRepository(clean_database)
    budget = 100
    per_call = 30

    results = await asyncio.gather(
        *[
            repository.reserve(usage_date=USAGE_DATE, tokens=per_call, budget=budget)
            for _ in range(10)
        ]
    )

    admitted = [value for value in results if value is not None]
    rejected = [value for value in results if value is None]

    assert len(admitted) == 3
    assert len(rejected) == 7

    snapshot = await repository.snapshot(usage_date=USAGE_DATE)
    assert snapshot.consumed_tokens == 3 * per_call
    assert snapshot.consumed_tokens <= budget
    assert snapshot.call_count == 3


@pytest.mark.asyncio
async def test_reconcile_converges_estimate_to_actual(clean_database: Database) -> None:
    repository = LlmBudgetRepository(clean_database)
    reserved = await repository.reserve(usage_date=USAGE_DATE, tokens=100, budget=1_000)
    assert reserved == 100

    await repository.reconcile(usage_date=USAGE_DATE, delta=60 - 100)

    snapshot = await repository.snapshot(usage_date=USAGE_DATE)
    assert snapshot.consumed_tokens == 60


@pytest.mark.asyncio
async def test_reconcile_does_not_go_negative(clean_database: Database) -> None:
    repository = LlmBudgetRepository(clean_database)
    await repository.reserve(usage_date=USAGE_DATE, tokens=10, budget=1_000)

    await repository.reconcile(usage_date=USAGE_DATE, delta=-9_999)

    snapshot = await repository.snapshot(usage_date=USAGE_DATE)
    assert snapshot.consumed_tokens == 0
