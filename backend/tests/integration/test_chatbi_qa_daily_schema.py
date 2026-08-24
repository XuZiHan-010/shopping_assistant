"""chatbi_qa_daily 的表结构与约束。"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000031")


async def _insert_merchant(session: AsyncSession) -> None:
    session.add(
        Merchant(
            id=MERCHANT_ID,
            merchant_code="chatbi-schema-merchant",
            display_name="Chat BI 结构测试商家",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_unique_grain_rejects_duplicate(db_session: AsyncSession) -> None:
    """移除唯一粒度约束时，本测试应失败并暴露重复汇总行。"""
    await _insert_merchant(db_session)
    insert_sql = text(
        "INSERT INTO chatbi_qa_daily "
        "(id, stat_date, merchant_id, category, answer_total) "
        "VALUES (gen_random_uuid(), DATE '2026-08-20', :mid, 'TRADE', 1)"
    )
    await db_session.execute(insert_sql, {"mid": MERCHANT_ID})
    await db_session.flush()

    with pytest.raises(IntegrityError):
        await db_session.execute(insert_sql, {"mid": MERCHANT_ID})
        await db_session.flush()


@pytest.mark.asyncio
async def test_counter_rejects_negative(db_session: AsyncSession) -> None:
    """移除非负计数约束时，本测试应失败并阻止脏汇总数据。"""
    await _insert_merchant(db_session)

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO chatbi_qa_daily "
                "(id, stat_date, merchant_id, category, answer_total) "
                "VALUES (gen_random_uuid(), DATE '2026-08-21', :mid, 'TRADE', -1)"
            ),
            {"mid": MERCHANT_ID},
        )
        await db_session.flush()
