"""演示环境商家切换端点。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_app_settings, get_merchant_repository
from app.core.config import Settings
from app.core.errors import error_responses
from app.repositories.merchant import MerchantRepository
from app.schemas.merchant import DemoMerchant, DemoMerchantListResponse

router = APIRouter(tags=["demo"])


@router.get(
    "/demo/merchants",
    response_model=DemoMerchantListResponse,
    responses=error_responses(404),
)
async def list_demo_merchants(
    settings: Annotated[Settings, Depends(get_app_settings)],
    repository: Annotated[MerchantRepository, Depends(get_merchant_repository)],
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
            display_name=by_id[merchant_id].display_name,
            token=token,
        )
        for token, merchant_id in settings.demo_merchant_tokens.items()
        if merchant_id in by_id
    ]
    return DemoMerchantListResponse(merchants=merchants)
