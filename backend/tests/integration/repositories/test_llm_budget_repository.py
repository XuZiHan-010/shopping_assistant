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
from tests.postgres import truncate_all_tables

USAGE_DATE = date(2026, 8, 6)


@pytest_asyncio.fixture
async def clean_database(integration_database: Database) -> AsyncIterator[Database]:
    """为仓储自行管理的事务显式清理数据库。"""

    async with integration_database.session() as session:
        await truncate_all_tables(session)
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


# ---------- N5 B 三级预算（PRD §10.2） ----------

from app.llm.budget_scope import BudgetScope  # noqa: E402


async def _consumed(database: Database, key: str) -> int:
    async with database.session() as session:
        value = await session.scalar(
            text(
                "SELECT consumed_tokens FROM llm_daily_budget "
                "WHERE usage_date = :d AND scope_key = :k"
            ),
            {"d": USAGE_DATE, "k": key},
        )
    return int(value or 0)


@pytest.mark.asyncio
async def test_scoped_reserve_is_all_or_nothing(clean_database: Database) -> None:
    """店铺级超额时，全局与角色级也不扣：任一级拒绝即整体回滚。"""

    repository = LlmBudgetRepository(clean_database)
    scopes = [
        BudgetScope("GLOBAL", 1_000),
        BudgetScope("ROLE:MERCHANT", 1_000),
        BudgetScope("SHOP:MERCHANT:a", 50),
    ]

    assert await repository.reserve_scoped(usage_date=USAGE_DATE, tokens=40, scopes=scopes) is None
    exhausted = await repository.reserve_scoped(usage_date=USAGE_DATE, tokens=40, scopes=scopes)

    assert exhausted == "SHOP:MERCHANT:a"
    assert await _consumed(clean_database, "GLOBAL") == 40
    assert await _consumed(clean_database, "ROLE:MERCHANT") == 40
    assert await _consumed(clean_database, "SHOP:MERCHANT:a") == 40


@pytest.mark.asyncio
async def test_concurrent_scoped_reserve_never_overspends_any_level(
    clean_database: Database,
) -> None:
    """两家店并发打同一个角色池：角色级先满，任何一级都不超发。"""

    repository = LlmBudgetRepository(clean_database)

    def scopes(shop: str) -> list[BudgetScope]:
        return [
            BudgetScope("GLOBAL", 10_000),
            BudgetScope("ROLE:CUSTOMER", 100),
            BudgetScope(f"SHOP:CUSTOMER:{shop}", 70),
        ]

    results = await asyncio.gather(
        *[
            repository.reserve_scoped(usage_date=USAGE_DATE, tokens=30, scopes=scopes(shop))
            for shop in ("a", "b") * 5
        ]
    )

    admitted = [result for result in results if result is None]
    assert len(admitted) == 3  # 角色池 100 只容得下 3 次 30
    assert await _consumed(clean_database, "ROLE:CUSTOMER") == 90
    assert await _consumed(clean_database, "GLOBAL") == 90
    assert await _consumed(clean_database, "SHOP:CUSTOMER:a") <= 70
    assert await _consumed(clean_database, "SHOP:CUSTOMER:b") <= 70


@pytest.mark.asyncio
async def test_reconcile_scoped_adjusts_every_level(clean_database: Database) -> None:
    repository = LlmBudgetRepository(clean_database)
    scopes = [BudgetScope("GLOBAL", 1_000), BudgetScope("ROLE:MERCHANT", 1_000)]
    await repository.reserve_scoped(usage_date=USAGE_DATE, tokens=100, scopes=scopes)

    await repository.reconcile_scoped(
        usage_date=USAGE_DATE, delta=-60, scope_keys=["GLOBAL", "ROLE:MERCHANT"]
    )

    assert await _consumed(clean_database, "GLOBAL") == 40
    assert await _consumed(clean_database, "ROLE:MERCHANT") == 40
