"""运维端点：暴露费用防护与限流的运行时状态，仅限管理员令牌访问。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.analytics.dates import business_today
from app.api.dependencies import get_app_settings, get_database, require_admin_token
from app.core.config import Settings
from app.core.errors import error_responses
from app.db.session import Database
from app.repositories.llm_budget import LlmBudgetRepository

router = APIRouter(prefix="/admin", tags=["admin"])


class OpsStatusResponse(BaseModel):
    """系统级聚合快照，不含商家标识、Token 明文或 Prompt 内容。"""

    llm_tokens_used_today: int
    llm_tokens_remaining_today: int
    llm_calls_today: int
    rate_limit_hits: int
    degraded_count: int
    error_code_counts: dict[str, int]
    agent_node_average_ms: dict[str, float]


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
    )
