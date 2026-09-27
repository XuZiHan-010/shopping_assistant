"""`DailyBriefRepository`：一商家一营业日一份，重新生成走版本替换（N3 阶段 C Task 2，D18⑥）。

**这一层只负责"版本递增存储"这个原语本身是并发安全的**（事务锁 + 唯一索引），
不负责"限流/冷却"——D18⑨「5 个并发重新生成请求最终只产生 1 个新版本」是**限流层**
的职责（大部分请求被 429 拒绝，只有 1 个真正调用到这一层），属于路由/服务层，
见 `tests/integration/v2/test_daily_brief_regenerate.py`。本文件只验证：多次
"确实被放行"的调用（例如限流窗口之外的连续调用）各自正确递增、不产生新行、
不因为并发写入互相覆盖丢失更新。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.models.memory_v2 import DailyBrief
from app.repositories.v2.daily_brief import DailyBriefRepository
from app.schemas.v2.merchant_ops import DailyBriefResponse

pytestmark = pytest.mark.integration

BUSINESS_DATE = date(2026, 9, 26)
NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


def _response(*, version: int, trigger: str = "SCHEDULED") -> DailyBriefResponse:
    return DailyBriefResponse(
        analysis_sources=[{"source": "DATABASE", "degraded": False, "degraded_reason": None}],
        thinking_steps=[], quality_status="NOT_RUN", quality_attempts=0, quality_notes=[],
        degraded=False, degraded_reason=None, brief_version=version, business_date=BUSINESS_DATE,
        business_timezone="Asia/Shanghai", data_as_of=NOW, generated_at=NOW, trigger=trigger,
        items=[], collapsed_count=0,
    )


async def _row(database: Database, merchant_id: UUID) -> DailyBrief:
    async with database.session() as session:
        row = await session.scalar(
            select(DailyBrief).where(
                DailyBrief.merchant_id == merchant_id, DailyBrief.business_date == BUSINESS_DATE
            )
        )
        assert row is not None
        return row


@pytest.mark.asyncio
async def test_get_current_returns_none_when_no_brief_exists(
    integration_database: Database, db_session: AsyncSession, merchant_one_id: UUID,
) -> None:
    await db_session.commit()
    async with integration_database.session() as session:
        result = await DailyBriefRepository(session).get_current(
            merchant_one_id, business_date=BUSINESS_DATE
        )
    assert result is None


@pytest.mark.asyncio
async def test_stage_or_replace_creates_first_version(
    integration_database: Database, db_session: AsyncSession, merchant_one_id: UUID,
) -> None:
    await db_session.commit()
    async with integration_database.session() as session:
        await DailyBriefRepository(session).stage_or_replace(
            merchant_one_id, business_date=BUSINESS_DATE, response=_response(version=1)
        )
        await session.commit()
    row = await _row(integration_database, merchant_one_id)
    assert row.brief_version == 1


@pytest.mark.asyncio
async def test_stage_or_replace_keeps_payload_version_in_sync_with_column(
    integration_database: Database, db_session: AsyncSession, merchant_one_id: UUID,
) -> None:
    """`row.payload["brief_version"]` 必须与 `row.brief_version` 列一致——调用方
    （路由层）序列化响应体时读的是 `payload`，如果两者不同步，返回给客户端的版本号
    就会停在传入时的占位值，永远不递增（真实发现的 bug，2026-09-26）。"""

    await db_session.commit()
    async with integration_database.session() as session:
        repo = DailyBriefRepository(session)
        await repo.stage_or_replace(
            merchant_one_id, business_date=BUSINESS_DATE, response=_response(version=1)
        )
        await session.commit()
    async with integration_database.session() as session:
        repo = DailyBriefRepository(session)
        # 故意传入一个错误的占位版本号（99），模拟调用方还不知道真实版本号时的情形。
        await repo.stage_or_replace(
            merchant_one_id, business_date=BUSINESS_DATE,
            response=_response(version=99, trigger="REGENERATED"),
        )
        await session.commit()

    row = await _row(integration_database, merchant_one_id)
    assert row.brief_version == 2
    assert row.payload["brief_version"] == 2  # 不是 99（调用方传入的占位值）


@pytest.mark.asyncio
async def test_stage_or_replace_bumps_version_not_row_count(
    integration_database: Database, db_session: AsyncSession, merchant_one_id: UUID,
) -> None:
    await db_session.commit()
    async with integration_database.session() as session:
        repo = DailyBriefRepository(session)
        await repo.stage_or_replace(
            merchant_one_id, business_date=BUSINESS_DATE, response=_response(version=1)
        )
        await session.commit()
    async with integration_database.session() as session:
        repo = DailyBriefRepository(session)
        await repo.stage_or_replace(
            merchant_one_id, business_date=BUSINESS_DATE,
            response=_response(version=2, trigger="REGENERATED"),
        )
        await session.commit()

    async with integration_database.session() as session:
        rows = (
            await session.scalars(
                select(DailyBrief).where(
                    DailyBrief.merchant_id == merchant_one_id,
                    DailyBrief.business_date == BUSINESS_DATE,
                )
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].brief_version == 2


@pytest.mark.asyncio
async def test_get_current_reflects_latest_version(
    integration_database: Database, db_session: AsyncSession, merchant_one_id: UUID,
) -> None:
    await db_session.commit()
    async with integration_database.session() as session:
        repo = DailyBriefRepository(session)
        await repo.stage_or_replace(
            merchant_one_id, business_date=BUSINESS_DATE, response=_response(version=1)
        )
        await session.commit()
    async with integration_database.session() as session:
        result = await DailyBriefRepository(session).get_current(
            merchant_one_id, business_date=BUSINESS_DATE
        )
    assert result is not None
    assert result.brief_version == 1


@pytest.mark.asyncio
async def test_concurrent_writes_never_lose_an_update(
    integration_database: Database, db_session: AsyncSession, merchant_one_id: UUID,
) -> None:
    """5 个并发的、都合法放行的写入各自生效——不因为竞态互相覆盖丢失更新
    （版本号从 1 恰好递增 5 次到 6，不多不少），且始终只有 1 行（不产生重复行）。

    限流层"大部分并发请求被拒绝"是另一层职责，见 `test_daily_brief_regenerate.py`；
    这里验证的是存储层原语本身在并发写入下的正确性。
    """

    await db_session.commit()
    async with integration_database.session() as session:
        await DailyBriefRepository(session).stage_or_replace(
            merchant_one_id, business_date=BUSINESS_DATE, response=_response(version=1)
        )
        await session.commit()

    async def _regenerate(attempt: int) -> None:
        async with integration_database.session() as session:
            await DailyBriefRepository(session).stage_or_replace(
                merchant_one_id, business_date=BUSINESS_DATE,
                response=_response(version=99, trigger="REGENERATED"),
            )
            await session.commit()
        del attempt

    await asyncio.gather(*[_regenerate(i) for i in range(5)])

    async with integration_database.session() as session:
        rows = (
            await session.scalars(
                select(DailyBrief).where(
                    DailyBrief.merchant_id == merchant_one_id,
                    DailyBrief.business_date == BUSINESS_DATE,
                )
            )
        ).all()
    assert len(rows) == 1  # 始终只有一行，不因为并发插入撞出重复行
    assert rows[0].brief_version == 6  # 1（初始）+ 5 次并发写入全部生效，无一丢失
