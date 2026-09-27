"""顾客端店铺、商品与券的公开浏览（PRD C1，契约 §8.8.2）。

四条都是**公开**端点：不读任何请求头凭证。店铺只由路径里的 `shop_slug` 在服务端解析，
未知与停用店铺、非本店与不可售商品都返回同一个 403，不泄露对象存在性（R5）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db_session, get_request_locale
from app.api.v2_deps import get_cursor_codec
from app.core.errors import ResourceForbiddenError, error_responses
from app.localization.locales import SupportedLocale
from app.repositories.merchant import MerchantRepository
from app.repositories.v2.catalog import CatalogReadRepository
from app.schemas.v2.common import CursorPage
from app.schemas.v2.shop_session import (
    CouponSummary,
    ProductDetailResponse,
    ProductSummary,
    StoreProfileResponse,
)
from app.services.v2.catalog import (
    ALLOWED_IMAGE_HOSTS,
    cached_product_translations,
    to_product_detail,
    to_product_summary,
)
from app.services.v2.coupons import is_active, to_coupon_summary
from app.services.v2.cursor import CursorCodec, CursorScope, descending

router = APIRouter(prefix="/v2/shop/stores", tags=["v2-shop-catalog"])

ShopSlugPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
]
#: 店铺规则摘要暂无数据来源；返回空串而不是编造一段摘要（R7）。
RULES_SUMMARY_UNAVAILABLE: Final = ""


async def resolve_shop(shop_slug: ShopSlugPath, session: AsyncSession) -> UUID:
    merchant_id = await MerchantRepository(session).get_active_by_shop_slug(shop_slug)
    if merchant_id is None:
        raise ResourceForbiddenError
    return merchant_id


def _public_scope(
    *, endpoint: str, resource: str, merchant_id: UUID, locale: SupportedLocale, limit: int
) -> CursorScope:
    """公开列表的游标绑定到端点 + 店铺 + 资源 + 语言 + 每页大小；没有会话主体。"""

    return CursorScope(
        endpoint=endpoint,
        role="PUBLIC",
        principal_digest="",
        merchant_id=str(merchant_id),
        resource=resource,
        filters={},
        locale=locale.value,
        limit=limit,
    )


def _newest_first(created_at: datetime, row_id: str) -> tuple[str, str]:
    return descending(created_at.isoformat()), descending(row_id)


@router.get(
    "/{shop_slug}",
    response_model=StoreProfileResponse,
    responses=error_responses(403, 422, 503),
)
async def get_store(
    shop_slug: ShopSlugPath,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> StoreProfileResponse:
    merchant_id = await resolve_shop(shop_slug, session)
    display_name, display_name_en = await CatalogReadRepository(session).shop_names(merchant_id)
    if locale is SupportedLocale.EN_US and display_name_en:
        display_name = display_name_en
    return StoreProfileResponse(
        shop_slug=shop_slug, display_name=display_name, rules_summary=RULES_SUMMARY_UNAVAILABLE
    )


@router.get(
    "/{shop_slug}/products",
    response_model=CursorPage[ProductSummary],
    responses=error_responses(403, 422, 503),
)
async def list_products(
    shop_slug: ShopSlugPath,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CursorPage[ProductSummary]:
    """只返回在售商品；排序 `created_at DESC, id DESC`。"""

    merchant_id = await resolve_shop(shop_slug, session)
    products = await CatalogReadRepository(session).on_sale_products(merchant_id)
    page = codec.page(
        products,
        key=lambda product: _newest_first(product.created_at, str(product.id)),
        scope=_public_scope(
            endpoint="shop.products.list",
            resource="PRODUCT",
            merchant_id=merchant_id,
            locale=locale,
            limit=limit,
        ),
        cursor=cursor,
        now=datetime.now(UTC),
    )
    translations = await cached_product_translations(
        session, merchant_id=merchant_id, products=page.items, locale=locale
    )
    return CursorPage[ProductSummary](
        items=[
            to_product_summary(
                product,
                allowed_image_hosts=ALLOWED_IMAGE_HOSTS,
                locale=locale,
                translations=translations,
            )
            for product in page.items
        ],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get(
    "/{shop_slug}/products/{product_id}",
    response_model=ProductDetailResponse,
    responses=error_responses(403, 422, 503),
)
async def get_product(
    shop_slug: ShopSlugPath,
    product_id: Annotated[str, Path(min_length=1, max_length=128)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
) -> ProductDetailResponse:
    merchant_id = await resolve_shop(shop_slug, session)
    try:
        product_uuid = UUID(product_id)
    except ValueError:
        # 形状不对的标识与「不存在」同一个结果：不让探测者区分两者。
        raise ResourceForbiddenError from None
    product = await CatalogReadRepository(session).on_sale_product(merchant_id, product_uuid)
    if product is None:
        raise ResourceForbiddenError
    translations = await cached_product_translations(
        session, merchant_id=merchant_id, products=[product], locale=locale, include_detail=True
    )
    return to_product_detail(
        product, allowed_image_hosts=ALLOWED_IMAGE_HOSTS, locale=locale, translations=translations
    )


@router.get(
    "/{shop_slug}/coupons",
    response_model=CursorPage[CouponSummary],
    responses=error_responses(403, 422, 503),
)
async def list_coupons(
    shop_slug: ShopSlugPath,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    codec: Annotated[CursorCodec, Depends(get_cursor_codec)],
    locale: Annotated[SupportedLocale, Depends(get_request_locale)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CursorPage[CouponSummary]:
    """仅当前已生效券（`starts_at ≤ now < ends_at` 且未停用）。"""

    merchant_id = await resolve_shop(shop_slug, session)
    now = datetime.now(UTC)
    coupons = await CatalogReadRepository(session).coupons(merchant_id)
    live = [row for row in coupons if is_active(row, now=now)]
    page = codec.page(
        live,
        key=lambda row: _newest_first(row.created_at, row.id),
        scope=_public_scope(
            endpoint="shop.coupons.list",
            resource="COUPON",
            merchant_id=merchant_id,
            locale=locale,
            limit=limit,
        ),
        cursor=cursor,
        now=now,
    )
    return CursorPage[CouponSummary](
        items=[to_coupon_summary(row) for row in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )
