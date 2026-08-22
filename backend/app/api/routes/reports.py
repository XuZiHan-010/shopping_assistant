"""每日经营日报端点。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import enforce_rate_limit, get_daily_report_service, get_merchant_context
from app.core.errors import error_responses
from app.core.security import MerchantContext
from app.schemas.report import DailyReportResponse
from app.services.report_service import DailyReportService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/daily",
    response_model=DailyReportResponse,
    responses=error_responses(401, 422, 429, 500, 503),
)
async def get_daily_report(
    context: Annotated[MerchantContext, Depends(get_merchant_context)],
    _: Annotated[None, Depends(enforce_rate_limit)],
    service: Annotated[DailyReportService, Depends(get_daily_report_service)],
) -> DailyReportResponse:
    """返回当前已验证商家的业务时区昨日经营日报。"""

    return await service.get_or_create(context.merchant_id)
