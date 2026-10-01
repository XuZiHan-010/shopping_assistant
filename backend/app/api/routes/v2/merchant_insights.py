"""首页经营主指标（W 阶段 Task 2，PRD M1，契约 §8.12.4）：`GET /api/v2/merchant/metrics/overview`。

只读、零 LLM：数字全部来自 `AttributionService` 的确定性查询（R4），`merchant_id`
只从商家会话解析（R5）；周期由后端固定，不接受任何日期或商家参数。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_app_settings, get_database, get_request_locale
from app.api.session_deps import require_merchant_session
from app.core.config import Settings
from app.core.errors import error_responses
from app.core.security import MerchantContext
from app.core.session import SessionContext
from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.repositories.analytics import AnalyticsRepository
from app.schemas.v2.merchant_ops import MerchantMetricsOverviewResponse
from app.services.safe_query import SafeQueryService
from app.services.v2.attribution import AttributionService
from app.services.v2.metrics_overview import build_metrics_overview

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-insights"])


def get_overview_now() -> datetime:
    """「现在」的唯一来源；测试通过 `dependency_overrides` 冻结时钟。"""

    return datetime.now(UTC)


@router.get(
    "/metrics/overview",
    response_model=MerchantMetricsOverviewResponse,
    # 契约只列 401/403/503；422 仍须声明，否则 FastAPI 为 X-Session-Id 头参数默认注入的
    # 校验错误响应会走 HTTPValidationError 而不是 ErrorResponse（同当日简报端点）。
    responses=error_responses(401, 403, 422, 503),
)
async def get_metrics_overview(
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    now: Annotated[datetime, Depends(get_overview_now)],
) -> MerchantMetricsOverviewResponse:
    timezone = settings.business_timezone

    @asynccontextmanager
    async def scope() -> AsyncIterator[AttributionService]:
        # 每个分项独立会话：一个分项的 SQL 失败不会污染其余分项的事务。
        async with database.session() as session:
            yield AttributionService(
                SafeQueryService(AnalyticsRepository(session), business_timezone=timezone)
            )

    return await build_metrics_overview(
        scope,
        MerchantContext(merchant_id=ctx.merchant_id),
        now=now,
        business_timezone=timezone,
        locale=locale,
    )
