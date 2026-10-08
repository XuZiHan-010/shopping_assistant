"""成本绑定价格版本（N5 B Task 2；PRD §10.2）：写入时按当时价格算好存下，价格表只追加。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.session import Database
from app.models.operations import LlmUsage, ModelPriceVersion
from app.repositories.llm_budget import LlmBudgetRepository
from tests.postgres import truncate_all_tables

pytestmark = pytest.mark.integration

DAY1 = datetime(2026, 10, 10, 2, 0, tzinfo=UTC)  # 周六，非高峰
PEAK = datetime(2026, 10, 12, 2, 0, tzinfo=UTC)  # 周一 02:00，高峰
DAY2 = datetime(2026, 11, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def clean_database(integration_database: Database) -> AsyncIterator[Database]:
    async with integration_database.session() as session:
        await truncate_all_tables(session)
        await session.commit()
    yield integration_database


async def _record(repo: LlmBudgetRepository, *, at: datetime, model: str = "deepseek-flash") -> str:
    request_id = f"req-{uuid4().hex[:8]}"
    await repo.record_usage(
        usage_date=at.date(),
        request_id=request_id,
        model=model,
        input_tokens=1_000_000,
        output_tokens=500_000,
        total_tokens=1_500_000,
        reserved_tokens=1_500_000,
        usage_known=True,
        failure_kind=None,
        status="SUCCEEDED",
        merchant_id=None,
        role="MERCHANT",
        cache_hit_tokens=400_000,
        at=at,
    )
    return request_id


async def _usage(database: Database, request_id: str) -> LlmUsage:
    async with database.session() as session:
        row = await session.scalar(select(LlmUsage).where(LlmUsage.request_id == request_id))
    assert row is not None
    return row


async def test_usage_row_stores_cost_from_the_version_in_effect(clean_database: Database) -> None:
    repo = LlmBudgetRepository(clean_database)

    off_peak = await _usage(clean_database, await _record(repo, at=DAY1))
    peak = await _usage(clean_database, await _record(repo, at=PEAK))

    # 0.4M×0.003 + 0.6M×0.15 + 0.5M×0.6（非高峰）；高峰正好两倍
    assert off_peak.cost == Decimal("0.39120000")
    assert peak.cost == Decimal("0.78240000")
    assert (off_peak.price_period, peak.price_period) == ("OFF_PEAK", "PEAK")
    assert off_peak.cost_currency == "USD"
    assert off_peak.role == "MERCHANT" and off_peak.cache_hit_tokens == 400_000
    assert off_peak.price_version_id is not None


def _version(model: str, price: str, effective_from: datetime) -> ModelPriceVersion:
    value = Decimal(price)
    return ModelPriceVersion(
        model=model,
        currency="USD",
        peak_cache_hit=value,
        peak_cache_miss=value,
        peak_output=value,
        off_peak_cache_hit=value,
        off_peak_cache_miss=value,
        off_peak_output=value,
        effective_from=effective_from,
        source_note="test-only price",
    )


async def test_historical_cost_unchanged_after_price_update(clean_database: Database) -> None:
    # 价格表只追加、测试间不清理：用本测试独有的模型名，避免污染真实模型的价格版本。
    model = f"test-model-{uuid4().hex[:8]}"
    async with clean_database.session() as session:
        session.add(_version(model, "1", datetime(2026, 10, 1, tzinfo=UTC)))
        await session.commit()
    repo = LlmBudgetRepository(clean_database)
    before = await _usage(clean_database, await _record(repo, at=DAY1, model=model))

    async with clean_database.session() as session:
        session.add(_version(model, "9.99", DAY2))
        await session.commit()

    assert (await _usage(clean_database, before.request_id)).cost == before.cost
    later = datetime(2026, 11, 7, 2, tzinfo=UTC)
    after = await _usage(clean_database, await _record(repo, at=later, model=model))
    assert after.cost != before.cost
    assert after.price_version_id != before.price_version_id


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE model_price_versions SET peak_output = 0",
        "DELETE FROM model_price_versions",
    ],
)
async def test_price_rows_are_append_only(clean_database: Database, statement: str) -> None:
    async with clean_database.session() as session:
        with pytest.raises(DBAPIError, match="只允许追加"):
            await session.execute(text(statement))
        await session.rollback()


async def test_unknown_model_and_unknown_usage_stay_unpriced(clean_database: Database) -> None:
    repo = LlmBudgetRepository(clean_database)
    unknown_model = await _usage(
        clean_database, await _record(repo, at=DAY1, model="no-such-model")
    )
    await repo.record_usage(
        usage_date=date(2026, 10, 10),
        request_id="timeout-1",
        model="deepseek-flash",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        reserved_tokens=500,
        usage_known=False,
        failure_kind=None,
        status="FAILED",
        merchant_id=None,
        at=DAY1,
    )
    unknown_usage = await _usage(clean_database, "timeout-1")

    assert unknown_model.cost is None and unknown_model.price_version_id is None
    assert unknown_usage.cost is None  # 未定价不是 0
