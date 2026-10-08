"""PostgreSQL 中原子管理每日 LLM 费用预算。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.db.session import Database
from app.llm.budget_scope import GLOBAL_SCOPE, BudgetScope
from app.llm.pricing import PriceVersion, price_period, usage_cost
from app.models.answer import Answer
from app.models.operations import LlmDailyBudget, LlmUsage, ModelPriceVersion


@dataclass(frozen=True)
class DailyBudgetSnapshot:
    consumed_tokens: int
    call_count: int


@dataclass(frozen=True)
class LlmOpsOverview:
    """运维看板用的当日聚合（N5 B Task 3）；不含任何请求正文、Prompt 或经营数据。"""

    scope_usage: dict[str, int]
    cost_by_currency: dict[str, Decimal]
    unpriced_calls: int
    cache_hit_tokens: int
    input_tokens: int


@dataclass(frozen=True)
class TurnStats:
    """当日对话回合的聚合（验收 §12.6）：只有计数与合计，不含正文、提问或任何主体标识。"""

    #: 发生过模型调用的回合数：`purpose = AGENT` 的不同追踪 ID 数。
    turns: int
    agent_tokens: int
    agent_cost_by_currency: dict[str, Decimal]
    #: 当日已完成回答的平均耗时（毫秒）；没有回答时为 None。
    avg_elapsed_ms: float | None


class LlmBudgetRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def reserve(self, *, usage_date: date, tokens: int, budget: int) -> int | None:
        """只按全局级原子预扣（迁移期保留的单级入口）；返回扣后用量，超额返回 None。"""

        exhausted = await self.reserve_scoped(
            usage_date=usage_date, tokens=tokens, scopes=[BudgetScope(GLOBAL_SCOPE, budget)]
        )
        if exhausted is not None:
            return None
        return (await self.snapshot(usage_date=usage_date)).consumed_tokens

    async def reserve_scoped(
        self, *, usage_date: date, tokens: int, scopes: Sequence[BudgetScope]
    ) -> str | None:
        """在**一个事务**里同时预扣各级预算；任一级超额则整体回滚并返回该级的 key。

        PostgreSQL 在行锁后重算 `WHERE consumed_tokens + :tokens <= :budget`，并发不会超发；
        按 key 排序加锁，避免两个请求以相反顺序锁同一组行而死锁。成功返回 None。
        """

        ordered = sorted(scopes, key=lambda scope: scope.key)
        async with self._database.session() as session, session.begin():
            for scope in ordered:
                await session.execute(
                    insert(LlmDailyBudget)
                    .values(usage_date=usage_date, scope_key=scope.key)
                    .on_conflict_do_nothing(constraint="uq_llm_daily_budget_scope")
                )
            for scope in ordered:
                result = await session.execute(
                    text(
                        "UPDATE llm_daily_budget SET consumed_tokens = consumed_tokens + :tokens, "
                        "call_count = call_count + 1, updated_at = now() "
                        "WHERE usage_date = :usage_date AND scope_key = :scope_key "
                        "AND consumed_tokens + :tokens <= :budget "
                        "RETURNING consumed_tokens"
                    ),
                    {
                        "usage_date": usage_date,
                        "scope_key": scope.key,
                        "tokens": tokens,
                        "budget": scope.budget,
                    },
                )
                if result.scalar_one_or_none() is None:
                    await session.rollback()
                    return scope.key
        return None

    async def reconcile(self, *, usage_date: date, delta: int) -> None:
        await self.reconcile_scoped(usage_date=usage_date, delta=delta, scope_keys=[GLOBAL_SCOPE])

    async def reconcile_scoped(
        self, *, usage_date: date, delta: int, scope_keys: Sequence[str]
    ) -> None:
        async with self._database.session() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE llm_daily_budget SET consumed_tokens = "
                    "GREATEST(consumed_tokens + :delta, 0), updated_at = now() "
                    "WHERE usage_date = :usage_date AND scope_key = ANY(:scope_keys)"
                ),
                {"usage_date": usage_date, "delta": delta, "scope_keys": list(scope_keys)},
            )

    async def snapshot(self, *, usage_date: date) -> DailyBudgetSnapshot:
        async with self._database.session() as session:
            row = await session.scalar(
                select(LlmDailyBudget).where(
                    LlmDailyBudget.usage_date == usage_date,
                    LlmDailyBudget.scope_key == GLOBAL_SCOPE,
                )
            )
            if row is None:
                return DailyBudgetSnapshot(consumed_tokens=0, call_count=0)
            return DailyBudgetSnapshot(
                consumed_tokens=int(row.consumed_tokens), call_count=int(row.call_count)
            )

    async def ops_overview(self, *, usage_date: date) -> LlmOpsOverview:
        async with self._database.session() as session:
            scopes = (
                await session.execute(
                    select(LlmDailyBudget.scope_key, LlmDailyBudget.consumed_tokens).where(
                        LlmDailyBudget.usage_date == usage_date
                    )
                )
            ).all()
            costs = (
                await session.execute(
                    select(LlmUsage.cost_currency, func.sum(LlmUsage.cost))
                    .where(LlmUsage.usage_date == usage_date, LlmUsage.cost.is_not(None))
                    .group_by(LlmUsage.cost_currency)
                )
            ).all()
            totals = (
                await session.execute(
                    select(
                        func.count().filter(LlmUsage.cost.is_(None)),
                        func.coalesce(func.sum(LlmUsage.cache_hit_tokens), 0),
                        func.coalesce(func.sum(LlmUsage.input_tokens), 0),
                    ).where(LlmUsage.usage_date == usage_date)
                )
            ).one()
        return LlmOpsOverview(
            scope_usage={str(key): int(used) for key, used in scopes},
            cost_by_currency={str(currency): Decimal(total) for currency, total in costs},
            unpriced_calls=int(totals[0]),
            cache_hit_tokens=int(totals[1]),
            input_tokens=int(totals[2]),
        )

    async def turn_stats(
        self, *, usage_date: date, day_start: datetime, day_end: datetime
    ) -> TurnStats:
        """`usage_date` 是业务日；`day_start` / `day_end` 是它在 UTC 上的起止，用来圈定回答。"""

        agent = (LlmUsage.usage_date == usage_date, LlmUsage.purpose == "AGENT")
        async with self._database.session() as session:
            turns, tokens = (
                await session.execute(
                    select(
                        func.count(func.distinct(LlmUsage.request_id)),
                        func.coalesce(func.sum(LlmUsage.total_tokens), 0),
                    ).where(*agent)
                )
            ).one()
            costs = (
                await session.execute(
                    select(LlmUsage.cost_currency, func.sum(LlmUsage.cost))
                    .where(*agent, LlmUsage.cost.is_not(None))
                    .group_by(LlmUsage.cost_currency)
                )
            ).all()
            elapsed = await session.scalar(
                select(func.avg(Answer.elapsed_ms)).where(
                    Answer.created_at >= day_start,
                    Answer.created_at < day_end,
                    Answer.processing_status == "SUCCEEDED",
                    Answer.elapsed_ms.is_not(None),
                )
            )
        return TurnStats(
            turns=int(turns),
            agent_tokens=int(tokens),
            agent_cost_by_currency={str(currency): Decimal(total) for currency, total in costs},
            avg_elapsed_ms=float(elapsed) if elapsed is not None else None,
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
        purpose: str = "AGENT",
        role: str | None = None,
        cache_hit_tokens: int | None = None,
        at: datetime | None = None,
    ) -> None:
        """写一行用量；成本按调用时刻生效的价格版本**当场算好存下**（PRD §10.2）。

        用量未知（超时、断流）或找不到该模型的价格版本时，成本存 NULL 表示「未定价」，不记 0。
        """

        moment = at or datetime.now(UTC)
        async with self._database.session() as session:
            version = await session.scalar(
                select(ModelPriceVersion)
                .where(ModelPriceVersion.model == model, ModelPriceVersion.effective_from <= moment)
                .order_by(ModelPriceVersion.effective_from.desc())
                .limit(1)
            )
            cost: Decimal | None = None
            if version is not None and usage_known:
                try:
                    cost = usage_cost(
                        _price_version(version),
                        at=moment,
                        input_tokens=input_tokens,
                        cache_hit_tokens=cache_hit_tokens,
                        output_tokens=output_tokens,
                    )
                except ValueError:
                    cost = None  # 上游计数自相矛盾时宁可不定价，也不记一个错的数
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
                    purpose=purpose,
                    role=role,
                    cache_hit_tokens=cache_hit_tokens,
                    price_version_id=version.id if version is not None else None,
                    price_period=price_period(moment).value if version is not None else None,
                    cost=cost,
                    cost_currency=version.currency if cost is not None and version else None,
                )
            )
            await session.commit()


def _price_version(row: ModelPriceVersion) -> PriceVersion:
    return PriceVersion(
        id=row.id,
        model=row.model,
        currency=row.currency,
        peak_cache_hit=row.peak_cache_hit,
        peak_cache_miss=row.peak_cache_miss,
        peak_output=row.peak_output,
        off_peak_cache_hit=row.off_peak_cache_hit,
        off_peak_cache_miss=row.off_peak_cache_miss,
        off_peak_output=row.off_peak_output,
        effective_from=row.effective_from,
    )
