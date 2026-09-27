"""商家商品内容与优惠券运营只读面；事实、完整度和生效判断由后端给出。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_principal_secret, get_request_locale
from app.api.session_deps import require_merchant_session
from app.api.v2_deps import get_cursor_codec, merchant_cursor_scope
from app.core.errors import error_responses
from app.core.session import SessionContext
from app.localization.locales import SupportedLocale
from app.repositories.v2.catalog import CatalogReadRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.merchant_ops import MerchantCoupon, MerchantProductContent
from app.services.v2.content_completeness import (
    missing_content_fields,
    missing_required_attributes,
)
from app.services.v2.coupons import is_active, to_coupon_summary
from app.services.v2.cursor import CursorCodec, descending

router = APIRouter(prefix="/v2/merchant", tags=["v2-merchant-catalog"])


def _newest_first(created_at: datetime, row_id: object) -> tuple[str, str]:
    return descending(created_at.isoformat()), descending(str(row_id))


@router.get(
    "/products/content",
    response_model=CursorPage[MerchantProductContent],
    responses=error_responses(401, 403, 422, 503),
)
async def list_product_content(
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CursorPage[MerchantProductContent]:
    now = datetime.now(UTC)
    rows = await CatalogReadRepository(session).merchant_products(ctx.merchant_id)
    scope = merchant_cursor_scope(
        ctx,
        endpoint="merchant.products.content",
        resource="PRODUCT",
        filters={},
        locale=locale,
        limit=limit,
        secret=principal_secret,
    )
    page = codec.page(
        rows,
        key=lambda row: _newest_first(row.created_at, row.id),
        scope=scope,
        cursor=cursor,
        now=now,
    )
    items = []
    for row in page.items:
        missing = sorted(
            missing_required_attributes(category=row.category, attributes=row.attributes)
        )
        missing_fields = sorted(missing_content_fields(
            category=row.category, detail_description=row.detail_description,
            image_url=row.image_url,
        ))
        items.append(
            MerchantProductContent(
                id=str(row.id),
                title=row.title,
                category=row.category,
                status=row.status,
                content_version=row.content_version,
                missing_required_attributes=missing,
                missing_content_fields=missing_fields,
                content_complete=not missing and not missing_fields,
                stock_on_hand=row.stock_on_hand,
                stock_reserved=row.stock_reserved,
                stock_available=row.stock_available,
            )
        )
    return CursorPage[MerchantProductContent](
        items=items, next_cursor=page.next_cursor, has_more=page.has_more
    )


@router.get(
    "/coupons",
    response_model=CursorPage[MerchantCoupon],
    responses=error_responses(401, 403, 422, 503),
)
async def list_merchant_coupons(
    ctx: Annotated[SessionContext, Depends(require_merchant_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    principal_secret: Annotated[bytes, Depends(get_principal_secret)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CursorPage[MerchantCoupon]:
    now = datetime.now(UTC)
    rows = await CatalogReadRepository(session).coupons(ctx.merchant_id)
    scope = merchant_cursor_scope(
        ctx,
        endpoint="merchant.coupons",
        resource="COUPON",
        filters={},
        locale=locale,
        limit=limit,
        secret=principal_secret,
    )
    page = codec.page(
        rows,
        key=lambda row: _newest_first(row.created_at, row.id),
        scope=scope,
        cursor=cursor,
        now=now,
    )
    return CursorPage[MerchantCoupon](
        items=[
            MerchantCoupon(
                **to_coupon_summary(row).model_dump(),
                state=row.state,
                currently_active=is_active(row, now=now),
            )
            for row in page.items
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )
