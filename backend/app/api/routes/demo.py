"""演示环境商家切换端点。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_app_settings, get_merchant_repository, get_request_locale
from app.core.config import Settings
from app.core.errors import error_responses
from app.localization.locales import SupportedLocale
from app.repositories.merchant import MerchantRepository, MerchantSummary
from app.schemas.merchant import DemoMerchant, DemoMerchantListResponse

router = APIRouter(tags=["demo"])


def _display_name(summary: MerchantSummary, locale: SupportedLocale) -> str:
    """零 LLM：按请求语言在两个已经人工维护好的展示名列之间二选一，缺失
    英文展示名时回退中文源展示名，绝不调用模型生成或猜测（Step 6）。"""

    if locale is SupportedLocale.EN_US and summary.display_name_en:
        return summary.display_name_en
    return summary.display_name


@router.get(
    "/demo/merchants",
    response_model=DemoMerchantListResponse,
    responses=error_responses(404),
)
async def list_demo_merchants(
    settings: Annotated[Settings, Depends(get_app_settings)],
    repository: Annotated[MerchantRepository, Depends(get_merchant_repository)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> DemoMerchantListResponse:
    """返回受控演示商家及其权限受限 Token。"""

    if not settings.demo_merchants_endpoint_enabled:
        raise HTTPException(status_code=404)

    configured_ids = list(settings.demo_merchant_tokens.values())
    summaries = await repository.list_demo_by_ids(configured_ids)
    by_id = {summary.merchant_id: summary for summary in summaries}
    merchants = [
        DemoMerchant(
            merchant_id=merchant_id,
            display_name=_display_name(by_id[merchant_id], locale),
            token=token,
        )
        for token, merchant_id in settings.demo_merchant_tokens.items()
        if merchant_id in by_id
    ]
    return DemoMerchantListResponse(merchants=merchants)
