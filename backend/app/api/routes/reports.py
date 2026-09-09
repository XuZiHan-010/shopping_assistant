"""每日经营日报端点。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.analytics.dates import business_today
from app.api.dependencies import (
    enforce_rate_limit,
    get_app_settings,
    get_daily_report_service,
    get_database,
    get_merchant_context,
    get_merchant_repository,
    get_request_locale,
    require_admin_token,
)
from app.core.config import Settings
from app.core.errors import (
    AdminForbiddenError,
    InvalidRequestError,
    ResourceNotFoundError,
    error_responses,
)
from app.core.security import MerchantContext
from app.db.session import Database
from app.localization.locales import SupportedLocale
from app.repositories.audit import AuditRepository
from app.repositories.merchant import MerchantRepository
from app.schemas.report import DailyReportRecomputeRequest, DailyReportResponse
from app.services.report_service import DailyReportService

router = APIRouter(prefix="/reports", tags=["reports"])
admin_router = APIRouter(prefix="/admin/reports", tags=["admin"])


@router.get(
    "/daily",
    response_model=DailyReportResponse,
    responses=error_responses(401, 422, 429, 500, 503),
)
async def get_daily_report(
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    _: Annotated[None, Depends(enforce_rate_limit)],
    service: Annotated[DailyReportService, Depends(get_daily_report_service)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> DailyReportResponse:
    """返回当前已验证商家的业务时区昨日经营日报。"""

    return await service.get_or_create(context.merchant_id, locale=locale)


@admin_router.post(
    "/daily/recompute",
    response_model=DailyReportResponse,
    responses=error_responses(401, 403, 404, 409, 422, 503),
)
async def recompute_daily_report(
    payload: DailyReportRecomputeRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    database: Annotated[Database, Depends(get_database)],
    merchants: Annotated[MerchantRepository, Depends(get_merchant_repository)],
    service: Annotated[DailyReportService, Depends(get_daily_report_service)],
    _admin: Annotated[None, Depends(require_admin_token)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> DailyReportResponse:
    """管理员显式替换一个演示商家的历史日报缓存。"""

    if await merchants.get_display_name(payload.merchant_id) is None:
        raise ResourceNotFoundError("商家")
    if payload.merchant_id not in set(settings.demo_merchant_tokens.values()):
        raise AdminForbiddenError()

    today = business_today(datetime.now(UTC), timezone=settings.business_timezone)
    oldest_allowed = today - timedelta(days=179)
    if not oldest_allowed <= payload.report_date <= today:
        raise InvalidRequestError("report_date 必须位于最近 180 个业务日内")

    response = await service.recompute(payload.merchant_id, payload.report_date, locale=locale)
    await AuditRepository(database).record_admin_action(
        merchant_id=payload.merchant_id,
        event_type="DAILY_REPORT_RECOMPUTED",
        resource_type="daily_report",
        resource_id=payload.report_date.isoformat(),
        request_id=str(request.state.request_id),
        metadata={
            "reason": payload.reason,
            "report_date": payload.report_date.isoformat(),
        },
    )
    return response
