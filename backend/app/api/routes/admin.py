"""运维端点：暴露费用防护与限流的运行时状态，仅限管理员令牌访问。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.analytics.dates import business_today
from app.api.dependencies import get_app_settings, get_database, require_admin_token
from app.core.config import Settings
from app.core.errors import error_responses
from app.db.session import Database
from app.repositories.llm_budget import LlmBudgetRepository

router = APIRouter(prefix="/admin", tags=["admin"])


class BudgetLevelStatus(BaseModel):
    """一级预算的当日用量（N5 B Task 3）。店铺级只给脱敏标识，不给商家 ID 或名称。"""

    level: Literal["GLOBAL", "ROLE", "SHOP"]
    scope: str
    budget_tokens: int = Field(ge=0)
    used_tokens: int = Field(ge=0)
    remaining_tokens: int = Field(ge=0)


class CostByCurrency(BaseModel):
    currency: str
    amount: str  # 十进制字符串，8 位小数；不用浮点表示金额


class OpsStatusResponse(BaseModel):
    """系统级聚合快照，不含商家标识、Token 明文或 Prompt 内容。"""

    llm_tokens_used_today: int
    llm_tokens_remaining_today: int
    llm_calls_today: int
    rate_limit_hits: int
    degraded_count: int
    error_code_counts: dict[str, int]
    agent_node_average_ms: dict[str, float]
    demo_deployment_mode: bool
    # N5 B Task 3 扩展（契约见后端计划 B7「运维端点」节）
    budget_levels: list[BudgetLevelStatus]
    llm_cost_today: list[CostByCurrency]
    unpriced_calls_today: int = Field(ge=0)
    cache_hit_tokens_today: int = Field(ge=0)
    cache_hit_rate_today: float | None
    tool_calls_total: int = Field(ge=0)
    tool_errors_total: int = Field(ge=0)
    route_p95_ms: dict[str, float]
    # 2026-10-04 扩展：每回合 token、成本、耗时与降级原因（验收 §12.6）。
    turns_today: int = Field(ge=0)
    avg_tokens_per_turn_today: float | None
    avg_cost_per_turn_today: list[CostByCurrency]
    avg_turn_elapsed_ms_today: float | None
    degraded_reason_counts: dict[str, int]
    source_degraded_counts: dict[str, int]


_SHOP_LEVEL_LIMIT = 20


def _budget_levels(settings: Settings, scope_usage: dict[str, int]) -> list[BudgetLevelStatus]:
    def row(
        level: Literal["GLOBAL", "ROLE", "SHOP"], scope: str, budget: int, used: int
    ) -> BudgetLevelStatus:
        return BudgetLevelStatus(
            level=level,
            scope=scope,
            budget_tokens=budget,
            used_tokens=used,
            remaining_tokens=max(budget - used, 0),
        )

    levels = [
        row("GLOBAL", "GLOBAL", settings.llm_daily_budget_tokens, scope_usage.get("GLOBAL", 0)),
        row(
            "ROLE",
            "ROLE:CUSTOMER",
            settings.llm_customer_daily_budget_tokens,
            scope_usage.get("ROLE:CUSTOMER", 0),
        ),
        row(
            "ROLE",
            "ROLE:MERCHANT",
            settings.llm_merchant_daily_budget_tokens,
            scope_usage.get("ROLE:MERCHANT", 0),
        ),
    ]
    shops = sorted(
        ((key, used) for key, used in scope_usage.items() if key.startswith("SHOP:")),
        key=lambda item: item[1],
        reverse=True,
    )[:_SHOP_LEVEL_LIMIT]
    for key, used in shops:
        _, role, merchant = key.split(":", 2)
        alias = hashlib.sha256(merchant.encode()).hexdigest()[:8]
        levels.append(
            row("SHOP", f"SHOP:{role}:{alias}", settings.llm_shop_daily_budget_tokens, used)
        )
    return levels


@router.get(
    "/ops/status",
    response_model=OpsStatusResponse,
    responses=error_responses(401, 403),
)
async def ops_status(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    _admin: Annotated[None, Depends(require_admin_token)],
) -> OpsStatusResponse:
    repository = LlmBudgetRepository(database)
    usage_date = business_today(datetime.now(UTC), timezone=settings.business_timezone)
    snapshot = await repository.snapshot(usage_date=usage_date)
    overview = await repository.ops_overview(usage_date=usage_date)
    day_start = datetime.combine(
        usage_date, time(0), ZoneInfo(settings.business_timezone)
    ).astimezone(UTC)
    turns = await repository.turn_stats(
        usage_date=usage_date, day_start=day_start, day_end=day_start + timedelta(days=1)
    )
    metrics = request.app.state.metrics
    return OpsStatusResponse(
        llm_tokens_used_today=snapshot.consumed_tokens,
        llm_tokens_remaining_today=max(
            settings.llm_daily_budget_tokens - snapshot.consumed_tokens, 0
        ),
        llm_calls_today=snapshot.call_count,
        rate_limit_hits=metrics.rate_limit_hits,
        degraded_count=metrics.degraded_count,
        error_code_counts=metrics.error_code_counts,
        agent_node_average_ms=metrics.agent_node_average_ms,
        demo_deployment_mode=settings.demo_deployment_mode,
        budget_levels=_budget_levels(settings, overview.scope_usage),
        llm_cost_today=[
            CostByCurrency(currency=currency, amount=f"{amount:.8f}")
            for currency, amount in sorted(overview.cost_by_currency.items())
        ],
        unpriced_calls_today=overview.unpriced_calls,
        cache_hit_tokens_today=overview.cache_hit_tokens,
        cache_hit_rate_today=(
            overview.cache_hit_tokens / overview.input_tokens if overview.input_tokens else None
        ),
        tool_calls_total=metrics.tool_calls_total,
        tool_errors_total=metrics.tool_errors_total,
        route_p95_ms=metrics.route_p95_ms,
        turns_today=turns.turns,
        # 没有回合时给 null：0 会被读成「每回合不花 token」。
        avg_tokens_per_turn_today=(turns.agent_tokens / turns.turns if turns.turns else None),
        avg_cost_per_turn_today=(
            [
                CostByCurrency(currency=currency, amount=f"{amount / turns.turns:.8f}")
                for currency, amount in sorted(turns.agent_cost_by_currency.items())
            ]
            if turns.turns
            else []
        ),
        avg_turn_elapsed_ms_today=turns.avg_elapsed_ms,
        degraded_reason_counts=metrics.degraded_reason_counts,
        source_degraded_counts=metrics.source_degraded_counts,
    )
