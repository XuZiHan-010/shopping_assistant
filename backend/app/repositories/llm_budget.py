"""PostgreSQL 中原子管理每日 LLM 费用预算。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.session import Database
from app.models.operations import LlmDailyBudget, LlmUsage


@dataclass(frozen=True)
class DailyBudgetSnapshot:
    consumed_tokens: int
    call_count: int


class LlmBudgetRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def reserve(self, *, usage_date: date, tokens: int, budget: int) -> int | None:
        """原子预扣。PostgreSQL 会在行锁后重算谓词，避免并发超发。"""
        async with self._database.session() as session, session.begin():
            await session.execute(
                insert(LlmDailyBudget)
                .values(usage_date=usage_date)
                .on_conflict_do_nothing(constraint="uq_llm_daily_budget_usage_date")
            )
            result = await session.execute(
                text(
                    "UPDATE llm_daily_budget SET consumed_tokens = consumed_tokens + :tokens, "
                    "call_count = call_count + 1, updated_at = now() "
                    "WHERE usage_date = :usage_date AND consumed_tokens + :tokens <= :budget "
                    "RETURNING consumed_tokens"
                ),
                {"usage_date": usage_date, "tokens": tokens, "budget": budget},
            )
            value = result.scalar_one_or_none()
            return int(value) if value is not None else None

    async def reconcile(self, *, usage_date: date, delta: int) -> None:
        async with self._database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE llm_daily_budget SET consumed_tokens = "
                    "GREATEST(consumed_tokens + :delta, 0), updated_at = now() "
                    "WHERE usage_date = :usage_date"
                ),
                {"usage_date": usage_date, "delta": delta},
            )

    async def snapshot(self, *, usage_date: date) -> DailyBudgetSnapshot:
        async with self._database.session() as session:
            row = await session.scalar(
                select(LlmDailyBudget).where(LlmDailyBudget.usage_date == usage_date)
            )
            if row is None:
                return DailyBudgetSnapshot(consumed_tokens=0, call_count=0)
            return DailyBudgetSnapshot(
                consumed_tokens=int(row.consumed_tokens), call_count=int(row.call_count)
            )

    async def record_usage(
        self,
        *,
        usage_date: date,
        request_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        reserved_tokens: int,
        usage_known: bool,
        failure_kind: str | None,
        status: str,
        merchant_id: UUID | None,
    ) -> None:
        async with self._database.session() as session:
            session.add(
                LlmUsage(
                    merchant_id=merchant_id,
                    request_id=request_id,
                    usage_date=usage_date,
                    model=model,
                    total_tokens=total_tokens,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    reserved_tokens=reserved_tokens,
                    usage_known=usage_known,
                    failure_kind=failure_kind,
                    status=status,
                )
            )
            await session.commit()
