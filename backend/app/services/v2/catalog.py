"""商品 ORM 到顾客端公开模型（契约 §8.8.1）的映射。

这里是「顾客能看到商品的什么」的唯一出口：库存只出三档，不出任何数量或阈值；
不出 `merchant_id`；图片地址只在结构安全且主机受信时放行，否则置空而不是让整条响应失败。
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.localization.locales import SupportedLocale, detect_source_language, hash_source_text
from app.models.analytics import Product
from app.prompts.localization import LOCALIZATION_PROMPT_VERSION
from app.repositories.localization import LocalizationRepository
from app.schemas.v2.common import yuan_to_cents
from app.schemas.v2.shop_session import (
    ProductAttribute,
    ProductDetailResponse,
    ProductSummary,
    is_trusted_image_host,
)
from app.services.v2.content_completeness import missing_required_attributes
from app.services.v2.stock_tier import stock_band

_ATTRIBUTE_SOURCES: Final = frozenset({"MERCHANT", "DEMO"})
#: 契约 §8.8.1：外部图片主机白名单缺配置时拒绝全部外部主机；目前尚无配置项。
#: 商品、购物车共用这一处，免得同一张图在两个页面一个显示一个不显示。
ALLOWED_IMAGE_HOSTS: Final[frozenset[str]] = frozenset()
TranslationStatus = Literal["SOURCE", "MACHINE", "FALLBACK"]
_NUMERIC_UNIT = re.compile(
    r"^\s*\d+(?:[.,]\d+)?\s*(?:mm|cm|m|km|mg|g|kg|ml|l|oz|lb|in|ft|%|°C|°F|pcs?)?\s*$",
    re.IGNORECASE,
)
_PRODUCT_CODE = re.compile(r"^(?=.*[0-9_/-])[A-Z0-9][A-Z0-9._/-]*$")


async def cached_product_translations(
    session: AsyncSession,
    *,
    merchant_id: UUID,
    products: Collection[Product],
    locale: SupportedLocale,
    include_detail: bool = False,
) -> dict[str, str]:
    """公开读取仅复用本店已有机器缓存；绝不在 GET 中调用模型。"""
    texts: set[str] = set()
    for product in products:
        if product.source_locale == locale.value:
            continue
        values = [product.title, product.short_description or ""]
        if include_detail:
            values.append(product.detail_description or "")
            for name, entry in product.attributes.items():
                if isinstance(entry, Mapping) and entry.get("source") in _ATTRIBUTE_SOURCES:
                    values.extend((name, entry.get("value", "")))
        texts.update(
            value
            for value in values
            if isinstance(value, str) and _needs_translation(value, locale)
        )
    if not texts:
        return {}
    hashes = {hash_source_text(value): value for value in texts}
    rows = await LocalizationRepository(session).get_merchant_machine_many(
        merchant_id=merchant_id,
        source_hashes=list(hashes),
        target_locale=locale,
        prompt_version=LOCALIZATION_PROMPT_VERSION,
    )
    now = datetime.now(UTC)
    return {
        hashes[source_hash]: row.translated_text
        for source_hash, row in rows.items()
        if row.expires_at > now
    }


def _needs_translation(value: str, locale: SupportedLocale) -> bool:
    if _NUMERIC_UNIT.fullmatch(value) or _PRODUCT_CODE.fullmatch(value.strip()):
        return False
    source = detect_source_language(value)
    return bool(value.strip()) and source.value not in (locale.value, "und")


def _localized(
    value: str,
    *,
    source_locale: str,
    locale: SupportedLocale,
    translations: Mapping[str, str],
    max_length: int,
) -> tuple[str, TranslationStatus]:
    if source_locale == locale.value or not _needs_translation(value, locale):
        return value, "SOURCE"
    translated = translations.get(value)
    if translated and translated.strip() and len(translated) <= max_length:
        return translated, "MACHINE"
    return value, "FALLBACK"


def trusted_image(url: str | None, allowed_hosts: Collection[str]) -> str | None:
    if url is None or not is_trusted_image_host(url, allowed_hosts):
        return None
    return url


def to_product_summary(
    product: Product,
    *,
    allowed_image_hosts: Collection[str],
    locale: SupportedLocale = SupportedLocale.ZH_CN,
    translations: Mapping[str, str] | None = None,
) -> ProductSummary:
    cached = translations or {}
    name, name_status = _localized(
        product.title,
        source_locale=product.source_locale,
        locale=locale,
        translations=cached,
        max_length=200,
    )
    short_description, short_status = _localized(
        product.short_description or "",
        source_locale=product.source_locale,
        locale=locale,
        translations=cached,
        max_length=500,
    )
    return ProductSummary(
        id=str(product.id),
        name=name,
        short_description=short_description,
        price_cents=yuan_to_cents(product.price),
        stock_band=stock_band(
            available=product.stock_available, low_stock_threshold=product.low_stock_threshold
        ),
        image_url=trusted_image(product.image_url, allowed_image_hosts),
        source_locale=product.source_locale,
        content_version=product.content_version,
        requested_locale=locale.value,
        name_translation_status=name_status,
        short_description_translation_status=short_status,
        category=product.category,
    )


def to_product_detail(
    product: Product,
    *,
    allowed_image_hosts: Collection[str],
    locale: SupportedLocale = SupportedLocale.ZH_CN,
    translations: Mapping[str, str] | None = None,
) -> ProductDetailResponse:
    cached = translations or {}
    summary = to_product_summary(
        product, allowed_image_hosts=allowed_image_hosts, locale=locale, translations=cached
    )
    description, description_status = _localized(
        product.detail_description or "",
        source_locale=product.source_locale,
        locale=locale,
        translations=cached,
        max_length=20_000,
    )
    return ProductDetailResponse(
        **summary.model_dump(),
        description=description,
        attributes=_attributes(
            product.attributes,
            fallback_updated_at=product.updated_at,
            source_locale=product.source_locale,
            locale=locale,
            translations=cached,
        ),
        description_translation_status=description_status,
        missing_attributes=sorted(
            missing_required_attributes(category=product.category, attributes=product.attributes)
        ),
    )


def _attributes(
    raw: Mapping[str, Any],
    *,
    fallback_updated_at: datetime,
    source_locale: str,
    locale: SupportedLocale,
    translations: Mapping[str, str],
) -> list[ProductAttribute]:
    """库内形状 `{名称: {value, source, updated_at}}`；来源不在白名单或值为空的条目不展示。"""

    items: list[ProductAttribute] = []
    source_names: list[str] = []
    for name, entry in raw.items():
        if not isinstance(entry, Mapping):
            continue
        value, source = entry.get("value"), entry.get("source")
        if not isinstance(value, str) or not value.strip() or source not in _ATTRIBUTE_SOURCES:
            continue
        translated_name, name_status = _localized(
            name,
            source_locale=source_locale,
            locale=locale,
            translations=translations,
            max_length=100,
        )
        translated_value, value_status = _localized(
            value,
            source_locale=source_locale,
            locale=locale,
            translations=translations,
            max_length=2_000,
        )
        updated_at = entry.get("updated_at")
        items.append(
            ProductAttribute(
                name=translated_name,
                value=translated_value,
                source=source,
                name_translation_status=name_status,
                value_translation_status=value_status,
                updated_at=(
                    datetime.fromisoformat(updated_at)
                    if isinstance(updated_at, str)
                    else fallback_updated_at
                ),
            )
        )
        source_names.append(name)
    if len({item.name for item in items}) != len(items):
        # 两个源键可以恰好译成同一个词；保留源键的唯一性，避免响应模型失败。
        return [
            item.model_copy(
                update={
                    "name": original,
                    "name_translation_status": (
                        "FALLBACK" if item.name != original else item.name_translation_status
                    ),
                }
            )
            for item, original in zip(items, source_names, strict=True)
        ]
    return items
