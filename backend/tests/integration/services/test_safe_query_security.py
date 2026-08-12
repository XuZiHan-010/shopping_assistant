"""B4 的安全验收。

每条对应计划 §B4 验收里的一行。这些性质一旦回归，泄漏和注入是静默发生的，
所以必须有独立用例，不能依赖上层测试顺带覆盖。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import MerchantContext
from app.intent.models import DateRange, QueryIntent
from app.models.analytics import Order
from app.repositories.analytics import AnalyticsRepository
from app.schemas.chat import AnswerMode, QuestionCategory
from app.services.safe_query import SafeQueryService, UnsupportedQueryError

NOW = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
DAY = date(2026, 8, 3)


def _service(session: AsyncSession) -> SafeQueryService:
    return SafeQueryService(AnalyticsRepository(session), business_timezone="Asia/Shanghai")


async def _order(session: AsyncSession, merchant_id: UUID, amount: str) -> None:
    session.add(
        Order(
            merchant_id=merchant_id,
            business_date=DAY,
            order_no=f"NO-{uuid4().hex[:8]}",
            buyer_key="buyer",
            order_status="COMPLETED",
            total_amount=Decimal(amount),
            paid_amount=Decimal(amount),
            placed_at=NOW,
            paid_at=NOW,
        )
    )
    await session.flush()


def _intent(**overrides: object) -> QueryIntent:
    base: dict[str, object] = {
        "answer_mode": AnswerMode.METRIC,
        "category": QuestionCategory.TRADE,
        "metric": "gmv",
        "dimensions": [],
        "filters": {},
        "date_range": DateRange(start=DAY, end=DAY),
    }
    base.update(overrides)
    return QueryIntent.model_validate(base)


@pytest.mark.asyncio
async def test_two_merchants_same_day_data_never_mix(
    db_session: AsyncSession, merchant_one_id: UUID, merchant_two_id: UUID
) -> None:
    """两个商家在同一天各下一单，金额不同——如果隔离失效，至少一边会读到

    对方的 999.00，而不是自己的 100.00。两个空集合互相比较不会暴露这类回归，
    所以两侧都必须有数据，且数据本身可区分。
    """

    await _order(db_session, merchant_one_id, "100.00")
    await _order(db_session, merchant_two_id, "999.00")

    first = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id), _intent(), now=NOW
    )
    second = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_two_id), _intent(), now=NOW
    )

    assert first.rows == [{"gmv": Decimal("100.00")}]
    assert second.rows == [{"gmv": Decimal("999.00")}]


@pytest.mark.asyncio
async def test_injection_in_filter_value_does_not_change_query_semantics(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await _order(db_session, merchant_one_id, "100.00")

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(filters={"order_status": "COMPLETED'; DROP TABLE orders; --"}),
        now=NOW,
    )

    assert result.rows == [{"gmv": None}]
    survived = await db_session.scalar(text("SELECT count(*) FROM orders"))
    assert survived == 1


@pytest.mark.asyncio
async def test_injection_in_metric_name_is_refused_before_reaching_sql(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    with pytest.raises(UnsupportedQueryError):
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(metric="gmv; DROP TABLE orders"),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_date_range_is_capped_at_180_days(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """180 天上限的调整说明由 `resolve_range` 产出为 `notes`，`SafeQueryService._plan_steps`

    把 `notes` 原样拼进 `plan_steps` 的末尾（见 `app/services/safe_query.py`
    `_plan_steps` 的 `*notes` 展开），所以断言可以直接对 `plan_steps` 生效，
    不需要改指向 `result.notes`——两个字段此时都带着这条说明。
    """

    result = await _service(db_session).execute(
        MerchantContext(merchant_id=merchant_one_id),
        _intent(date_range=DateRange(start=date(2024, 1, 1), end=DAY)),
        now=NOW,
    )

    assert any("180" in step for step in result.plan_steps)
    assert any("180" in note for note in result.notes)


@pytest.mark.asyncio
async def test_error_reason_never_leaks_sql_or_table_names(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    """数据库细节泄漏给用户既没用，又给攻击者送情报。"""

    with pytest.raises(UnsupportedQueryError) as error:
        await _service(db_session).execute(
            MerchantContext(merchant_id=merchant_one_id),
            _intent(metric="unknown_metric"),
            now=NOW,
        )

    reason = error.value.reason
    assert "orders" not in reason
    assert "SELECT" not in reason.upper()
    assert "psycopg" not in reason.lower()


@pytest.mark.asyncio
async def test_statement_timeout_is_active_on_the_request_session(
    db_session: AsyncSession,
) -> None:
    """没有 statement timeout，一条慢查询就能把连接池占满。

    直接问数据库当前会话的设置，而不是相信配置文件——`connect_args` 写错了
    也不会有任何报错，只会在某天变成一次线上事故。
    """

    timeout = await db_session.scalar(text("SHOW statement_timeout"))

    assert timeout not in {"0", "0ms", None}
