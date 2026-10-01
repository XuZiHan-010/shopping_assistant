"""顾客端店铺与商品公开浏览（PRD C1，契约 §8.8.2）。

全部是公开端点：不带任何请求头。真实 PostgreSQL——「只返回在售」「不泄露库存数量」
「非本店与不存在同一结构」只有在真库上跑才算数。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update

from app.db.session import Database
from app.localization.locales import SourceLanguage, SupportedLocale, hash_source_text
from app.models.analytics import Product
from app.models.localization import MachineTranslationCache
from app.models.merchant import Merchant
from app.models.promotion import Coupon
from app.prompts.localization import LOCALIZATION_PROMPT_VERSION
from app.repositories.localization import LocalizationRepository
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import seed_paid_order, seed_product

SHOP = "borough-api-100"
OTHER_SHOP = "borough-api-101"
QUANTITY_KEYS = ("stock_on_hand", "stock_reserved", "stock_available", "quantity", "threshold")


def _database(app: FastAPI) -> Database:
    return app.state.database  # type: ignore[no-any-return]


def _public_error(body: dict[str, Any]) -> dict[str, Any]:
    # request_id 每次请求都不同；比对其余字段才能说明两种情况「看起来一样」。
    return {key: value for key, value in body.items() if key != "request_id"}


async def _set_product(database: Database, product_id: UUID, **values: Any) -> None:
    async with database.session() as session:
        await session.execute(update(Product).where(Product.id == product_id).values(**values))
        await session.commit()


async def _seed_coupon(database: Database, merchant_id: UUID, **overrides: Any) -> UUID:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "merchant_id": merchant_id,
        "name": "满 100 减 10",
        "kind": "FULL_REDUCTION",
        "threshold_amount": Decimal("100.00"),
        "discount_amount": Decimal("10.00"),
        "discount_rate": None,
        "scope": "SHOP",
        "product_ids": [],
        "starts_at": now - timedelta(days=1),
        "ends_at": now + timedelta(days=1),
        "state": "ACTIVE",
    }
    values.update(overrides)
    async with database.session() as session:
        coupon = Coupon(**values)
        session.add(coupon)
        await session.commit()
        return coupon.id


async def _ok(client: AsyncClient, path: str, **params: Any) -> Any:
    resp = await client.get(path, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---- 店铺 -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_profile_is_public_and_hides_the_merchant_id(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}")

    assert body == {"shop_slug": SHOP, "display_name": "Borough商家100", "rules_summary": ""}
    assert str(MERCHANT_ONE_ID) not in json.dumps(body)


@pytest.mark.asyncio
async def test_store_profile_uses_the_english_name_when_maintained(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    async with _database(postgres_app).session() as session:
        await session.execute(
            update(Merchant)
            .where(Merchant.id == MERCHANT_ONE_ID)
            .values(display_name_en="Borough Store 100")
        )
        await session.commit()

    english = await postgres_client.get(
        f"/api/v2/shop/stores/{SHOP}", headers={"Accept-Language": "en-US"}
    )
    other = await postgres_client.get(
        f"/api/v2/shop/stores/{OTHER_SHOP}", headers={"Accept-Language": "en-US"}
    )

    assert english.json()["display_name"] == "Borough Store 100"
    assert other.json()["display_name"] == "Borough商家101"


@pytest.mark.asyncio
async def test_unknown_slug_is_indistinguishable_from_a_disabled_shop(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    async with _database(postgres_app).session() as session:
        await session.execute(
            update(Merchant).where(Merchant.id == MERCHANT_TWO_ID).values(status="DISABLED")
        )
        await session.commit()

    for suffix in ("", "/products", "/coupons"):
        unknown = await postgres_client.get(f"/api/v2/shop/stores/no-such-shop{suffix}")
        disabled = await postgres_client.get(f"/api/v2/shop/stores/{OTHER_SHOP}{suffix}")

        assert unknown.status_code == disabled.status_code == 403
        assert unknown.json()["code"] == "RESOURCE_FORBIDDEN"
        assert unknown.json()["details"] == []
        assert _public_error(unknown.json()) == _public_error(disabled.json())


@pytest.mark.asyncio
async def test_malformed_slug_is_a_validation_error(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    resp = await postgres_client.get("/api/v2/shop/stores/Not_A_Slug")

    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_REQUEST"


# ---- 商品详情 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_product_response_never_exposes_stock_quantity(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    product = await seed_product(_database(postgres_app), MERCHANT_ONE_ID, on_hand=3)

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products/{product}")

    flat = json.dumps(body)
    for leak in QUANTITY_KEYS:
        assert leak not in flat
    assert "merchant_id" not in flat and str(MERCHANT_ONE_ID) not in flat
    assert body["stock_band"] == "LOW_STOCK"


@pytest.mark.asyncio
async def test_product_detail_reports_missing_source_attributes(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await _set_product(
        database,
        product,
        category="鞋靴",
        attributes={
            "材质": {"value": "皮革", "source": "MERCHANT"},
            "尺码": {"value": "  ", "source": "MERCHANT"},
        },
    )

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products/{product}")

    assert body["missing_attributes"] == ["产地", "尺码"]
    assert all(item["name"] != "尺码" for item in body["attributes"])
    english = await postgres_client.get(
        f"/api/v2/shop/stores/{SHOP}/products/{product}",
        headers={"Accept-Language": "en-US"},
    )
    assert english.json()["missing_attributes"] == ["产地", "尺码"]
    listing = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products")
    assert all("missing_attributes" not in item for item in listing["items"])


@pytest.mark.asyncio
async def test_product_category_is_the_untranslated_source_value(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await _set_product(database, product, category="鞋靴")
    path = f"/api/v2/shop/stores/{SHOP}/products"

    detail = await _ok(postgres_client, f"{path}/{product}")
    listing = await _ok(postgres_client, path)
    english = await postgres_client.get(path, headers={"Accept-Language": "en-US"})

    assert detail["category"] == "鞋靴"
    assert [item["category"] for item in listing["items"]] == ["鞋靴"]
    # 类目不翻译：前端用固定词表显示，契约 §8.8.1。
    assert [item["category"] for item in english.json()["items"]] == ["鞋靴"]


@pytest.mark.asyncio
async def test_unregistered_category_has_no_required_attributes(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    product = await seed_product(_database(postgres_app), MERCHANT_ONE_ID)
    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products/{product}")
    assert body["missing_attributes"] == []


@pytest.mark.asyncio
async def test_popular_sort_uses_recent_paid_quantity(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    slow = await seed_product(database, MERCHANT_ONE_ID, title="慢销")
    hot = await seed_product(database, MERCHANT_ONE_ID, title="热销")
    warm = await seed_product(database, MERCHANT_ONE_ID, title="温和")
    await seed_paid_order(database, MERCHANT_ONE_ID, hot, quantity=5, days_ago=2)
    await seed_paid_order(database, MERCHANT_ONE_ID, warm, quantity=2, days_ago=3)
    await seed_paid_order(database, MERCHANT_ONE_ID, slow, quantity=9, days_ago=45)

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products", sort="popular")

    assert [item["name"] for item in body["items"]] == ["热销", "温和", "慢销"]
    assert "sales" not in json.dumps(body)


@pytest.mark.asyncio
async def test_popular_sort_ignores_other_shop_sales(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    mine = await seed_product(database, MERCHANT_ONE_ID, title="本店")
    older = await seed_product(database, MERCHANT_ONE_ID, title="本店旧品")
    await _set_product(database, older, created_at=datetime.now(UTC) - timedelta(days=30))
    foreign = await seed_product(database, MERCHANT_TWO_ID, title="别家")
    await seed_paid_order(database, MERCHANT_TWO_ID, foreign, quantity=50, days_ago=1)

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products", sort="popular")

    assert [item["id"] for item in body["items"]] == [str(mine), str(older)]


@pytest.mark.asyncio
async def test_popular_sort_without_sales_uses_newest(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    base = datetime.now(UTC)
    created = []
    for index in range(3):
        product = await seed_product(database, MERCHANT_ONE_ID, title=f"新品{index}")
        await _set_product(database, product, created_at=base - timedelta(minutes=10 - index))
        created.append(str(product))

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products", sort="popular")

    assert [item["id"] for item in body["items"]] == list(reversed(created))


@pytest.mark.asyncio
async def test_product_cursor_binds_sort(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    for index in range(3):
        await seed_product(database, MERCHANT_ONE_ID, title=f"甲{index}")
    path = f"/api/v2/shop/stores/{SHOP}/products"
    first = await _ok(postgres_client, path, limit=1)

    response = await postgres_client.get(
        path, params={"limit": 1, "sort": "popular", "cursor": first["next_cursor"]}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_CURSOR"


@pytest.mark.asyncio
async def test_unknown_product_sort_is_rejected(postgres_client: AsyncClient) -> None:
    response = await postgres_client.get(
        f"/api/v2/shop/stores/{SHOP}/products", params={"sort": "price"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stock_band_follows_available_stock(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    plenty = await seed_product(database, MERCHANT_ONE_ID, on_hand=63)
    reserved_out = await seed_product(database, MERCHANT_ONE_ID, on_hand=4, reserved=4)
    default_threshold = await seed_product(
        database, MERCHANT_ONE_ID, on_hand=5, low_stock_threshold=None
    )

    bands = {
        product: (await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products/{product}"))[
            "stock_band"
        ]
        for product in (plenty, reserved_out, default_threshold)
    }

    assert bands == {
        plenty: "IN_STOCK",
        reserved_out: "OUT_OF_STOCK",
        default_threshold: "LOW_STOCK",
    }


@pytest.mark.asyncio
async def test_product_detail_carries_content_and_attributes(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="棉质 T 恤", on_hand=40)
    await _set_product(
        database,
        product,
        short_description="夏季款",
        detail_description="纯棉面料。",
        image_url="/demo/products/01.png",
        content_version=3,
        attributes={
            "材质": {"value": "棉质", "source": "DEMO", "updated_at": "2026-09-01T02:00:00+00:00"},
            "来源不明": {"value": "x", "source": "MODEL"},
        },
    )

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products/{product}")

    assert body["id"] == str(product)
    assert body["name"] == "棉质 T 恤"
    assert body["short_description"] == "夏季款"
    assert body["description"] == "纯棉面料。"
    assert body["price_cents"] == 10000
    assert body["image_url"] == "/demo/products/01.png"
    assert body["content_version"] == 3
    assert body["attributes"] == [
        {
            "name": "材质",
            "value": "棉质",
            "source": "DEMO",
            "updated_at": "2026-09-01T02:00:00Z",
            "name_translation_status": "SOURCE",
            "value_translation_status": "SOURCE",
        }
    ]


@pytest.mark.asyncio
async def test_english_catalog_uses_only_current_merchant_cache_and_discloses_fallback(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="羊绒围巾")
    await _set_product(
        database,
        product,
        short_description="柔软保暖",
        detail_description="纯羊绒面料",
        content_version=3,
        source_locale="zh-CN",
        attributes={
            "材质": {"value": "羊绒", "source": "MERCHANT"},
            "尺寸": {"value": "20 cm", "source": "MERCHANT"},
        },
    )
    async with database.session() as session:
        cache = LocalizationRepository(session)
        for merchant_id, source, translated in (
            (MERCHANT_ONE_ID, "羊绒围巾", "Cashmere scarf"),
            (MERCHANT_ONE_ID, "柔软保暖", "Soft and warm"),
            (MERCHANT_ONE_ID, "材质", "Material"),
            (MERCHANT_ONE_ID, "羊绒", "Cashmere"),
            (MERCHANT_TWO_ID, "纯羊绒面料", "Other store private text"),
        ):
            await cache.upsert_machine(
                merchant_id=merchant_id,
                source_hash=hash_source_text(source),
                source_language=SourceLanguage.ZH_CN,
                target_locale=SupportedLocale.EN_US,
                translated_text=translated,
                model="fake",
                prompt_version=LOCALIZATION_PROMPT_VERSION,
            )
        await session.commit()

    path = f"/api/v2/shop/stores/{SHOP}/products/{product}"
    english = await postgres_client.get(path, headers={"Accept-Language": "en-US"})
    assert english.status_code == 200, english.text
    detail = english.json()
    assert detail["name"] == "Cashmere scarf"
    assert detail["short_description"] == "Soft and warm"
    assert detail["description"] == "纯羊绒面料"
    assert detail["source_locale"] == "zh-CN"
    assert detail["content_version"] == 3
    assert detail["requested_locale"] == "en-US"
    assert detail["name_translation_status"] == "MACHINE"
    assert detail["description_translation_status"] == "FALLBACK"
    attributes = {item["name"]: item for item in detail["attributes"]}
    assert attributes["Material"]["value"] == "Cashmere"
    assert attributes["Material"]["name_translation_status"] == "MACHINE"
    assert attributes["Material"]["value_translation_status"] == "MACHINE"
    assert attributes["尺寸"]["value"] == "20 cm"
    assert attributes["尺寸"]["value_translation_status"] == "SOURCE"

    listing = await postgres_client.get(
        f"/api/v2/shop/stores/{SHOP}/products", headers={"Accept-Language": "en-US"}
    )
    summary = next(item for item in listing.json()["items"] if item["id"] == str(product))
    assert summary["name"] == "Cashmere scarf"
    assert summary["name_translation_status"] == "MACHINE"

    await _set_product(database, product, title="新版围巾", content_version=4)
    stale = await postgres_client.get(path, headers={"Accept-Language": "en-US"})
    assert stale.json()["name"] == "新版围巾"
    assert stale.json()["name_translation_status"] == "FALLBACK"
    assert stale.json()["content_version"] == 4

    chinese = await postgres_client.get(path, headers={"Accept-Language": "zh-CN"})
    assert chinese.json()["name"] == "新版围巾"
    assert chinese.json()["name_translation_status"] == "SOURCE"


@pytest.mark.asyncio
async def test_numeric_unit_attribute_is_not_translated_even_if_cache_has_a_hit(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="Linen shirt")
    await _set_product(
        database,
        product,
        source_locale="en-US",
        attributes={"Length": {"value": "20 cm", "source": "MERCHANT"}},
    )
    async with database.session() as session:
        await LocalizationRepository(session).upsert_machine(
            merchant_id=MERCHANT_ONE_ID,
            source_hash=hash_source_text("20 cm"),
            source_language=SourceLanguage.EN_US,
            target_locale=SupportedLocale.ZH_CN,
            translated_text="错误翻译",
            model="fake",
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        await session.commit()

    response = await postgres_client.get(f"/api/v2/shop/stores/{SHOP}/products/{product}")
    assert response.status_code == 200, response.text
    value = response.json()["attributes"][0]
    assert value["value"] == "20 cm"
    assert value["value_translation_status"] == "SOURCE"


@pytest.mark.asyncio
async def test_colliding_translated_attribute_names_fall_back_to_distinct_source_names(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await _set_product(
        database,
        product,
        attributes={
            "材质": {"value": "棉", "source": "MERCHANT"},
            "面料": {"value": "麻", "source": "MERCHANT"},
        },
    )
    async with database.session() as session:
        cache = LocalizationRepository(session)
        for source in ("材质", "面料"):
            await cache.upsert_machine(
                merchant_id=MERCHANT_ONE_ID,
                source_hash=hash_source_text(source),
                source_language=SourceLanguage.ZH_CN,
                target_locale=SupportedLocale.EN_US,
                translated_text="Material",
                model="fake",
                prompt_version=LOCALIZATION_PROMPT_VERSION,
            )
        await session.commit()

    response = await postgres_client.get(
        f"/api/v2/shop/stores/{SHOP}/products/{product}",
        headers={"Accept-Language": "en-US"},
    )
    assert response.status_code == 200, response.text
    attributes = response.json()["attributes"]
    assert {item["name"] for item in attributes} == {"材质", "面料"}
    assert {item["name_translation_status"] for item in attributes} == {"FALLBACK"}


@pytest.mark.asyncio
async def test_uppercase_product_word_is_not_mistaken_for_a_sku(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="JACKET")
    await _set_product(database, product, source_locale="en-US")
    async with database.session() as session:
        await LocalizationRepository(session).upsert_machine(
            merchant_id=MERCHANT_ONE_ID,
            source_hash=hash_source_text("JACKET"),
            source_language=SourceLanguage.EN_US,
            target_locale=SupportedLocale.ZH_CN,
            translated_text="夹克",
            model="fake",
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        await session.commit()

    response = await postgres_client.get(f"/api/v2/shop/stores/{SHOP}/products/{product}")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "夹克"
    assert response.json()["name_translation_status"] == "MACHINE"


@pytest.mark.asyncio
async def test_overlong_cached_translation_falls_back_without_breaking_public_catalog(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="羊绒围巾")
    async with database.session() as session:
        await LocalizationRepository(session).upsert_machine(
            merchant_id=MERCHANT_ONE_ID,
            source_hash=hash_source_text("羊绒围巾"),
            source_language=SourceLanguage.ZH_CN,
            target_locale=SupportedLocale.EN_US,
            translated_text="x" * 201,
            model="fake",
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        await session.commit()

    response = await postgres_client.get(
        f"/api/v2/shop/stores/{SHOP}/products/{product}",
        headers={"Accept-Language": "en-US"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "羊绒围巾"
    assert response.json()["name_translation_status"] == "FALLBACK"


@pytest.mark.asyncio
async def test_expired_machine_translation_is_not_shown_as_current_product_copy(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="羊绒围巾")
    async with database.session() as session:
        cache = await LocalizationRepository(session).upsert_machine(
            merchant_id=MERCHANT_ONE_ID,
            source_hash=hash_source_text("羊绒围巾"),
            source_language=SourceLanguage.ZH_CN,
            target_locale=SupportedLocale.EN_US,
            translated_text="Cashmere scarf",
            model="fake",
            prompt_version=LOCALIZATION_PROMPT_VERSION,
        )
        await session.execute(
            update(MachineTranslationCache)
            .where(MachineTranslationCache.id == cache.id)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()

    response = await postgres_client.get(
        f"/api/v2/shop/stores/{SHOP}/products/{product}",
        headers={"Accept-Language": "en-US"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "羊绒围巾"
    assert response.json()["name_translation_status"] == "FALLBACK"


@pytest.mark.asyncio
async def test_untrusted_external_image_is_withheld(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """契约 §8.8.1：没有配置受信主机时拒绝全部外部图片；不让整条响应 500。"""

    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    await _set_product(database, product, image_url="https://images.example.com/a.png")

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products/{product}")

    assert body["image_url"] is None


@pytest.mark.asyncio
async def test_unavailable_products_share_one_forbidden_shape(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    """非本店、未上架、不存在、非法标识：顾客看到的是同一个 403（R5）。"""

    database = _database(postgres_app)
    theirs = await seed_product(database, MERCHANT_TWO_ID)
    offline = await seed_product(database, MERCHANT_ONE_ID, status="OFFLINE")

    bodies = []
    for product_id in (theirs, offline, uuid4(), "not-a-uuid"):
        resp = await postgres_client.get(f"/api/v2/shop/stores/{SHOP}/products/{product_id}")
        assert resp.status_code == 403, resp.text
        bodies.append(_public_error(resp.json()))

    assert bodies[0]["code"] == "RESOURCE_FORBIDDEN"
    assert all(body == bodies[0] for body in bodies)


# ---- 商品列表 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_product_list_only_shows_this_shops_online_products(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    online = await seed_product(database, MERCHANT_ONE_ID, title="在售")
    await seed_product(database, MERCHANT_ONE_ID, title="下架", status="OFFLINE")
    await seed_product(database, MERCHANT_ONE_ID, title="审核中", status="AUDITING")
    await seed_product(database, MERCHANT_TWO_ID, title="别人的")

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products")

    assert [item["id"] for item in body["items"]] == [str(online)]
    assert set(body["items"][0]) == {
        "id",
        "name",
        "short_description",
        "price_cents",
        "stock_band",
        "image_url",
        "source_locale",
        "content_version",
        "requested_locale",
        "name_translation_status",
        "short_description_translation_status",
        "category",  # 契约 §8.8.1：类目源值（WS 商品浮层与占位色）
    }
    assert body["has_more"] is False and body["next_cursor"] is None


@pytest.mark.asyncio
async def test_product_list_is_newest_first_and_pages_without_gaps(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    base = datetime.now(UTC)
    created = []
    for index in range(5):
        product = await seed_product(database, MERCHANT_ONE_ID, title=f"商品{index}")
        await _set_product(database, product, created_at=base - timedelta(minutes=10 - index))
        created.append(str(product))

    path = f"/api/v2/shop/stores/{SHOP}/products"
    first = await _ok(postgres_client, path, limit=2)
    second = await _ok(postgres_client, path, limit=2, cursor=first["next_cursor"])
    third = await _ok(postgres_client, path, limit=2, cursor=second["next_cursor"])

    seen = [item["id"] for page in (first, second, third) for item in page["items"]]
    assert seen == list(reversed(created))
    assert third["has_more"] is False and third["next_cursor"] is None


@pytest.mark.asyncio
async def test_product_cursor_is_bound_to_the_shop(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    for index in range(3):
        await seed_product(database, MERCHANT_ONE_ID, title=f"甲{index}")
        await seed_product(database, MERCHANT_TWO_ID, title=f"乙{index}")
    first = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/products", limit=1)

    resp = await postgres_client.get(
        f"/api/v2/shop/stores/{OTHER_SHOP}/products",
        params={"limit": 1, "cursor": first["next_cursor"]},
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_CURSOR"


# ---- 券 ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_active_coupons_listed(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    now = datetime.now(UTC)
    active = await _seed_coupon(database, MERCHANT_ONE_ID)
    day = timedelta(days=1)
    expired = await _seed_coupon(
        database, MERCHANT_ONE_ID, starts_at=now - 5 * day, ends_at=now - day
    )
    future = await _seed_coupon(
        database, MERCHANT_ONE_ID, starts_at=now + day, ends_at=now + 5 * day
    )
    disabled = await _seed_coupon(database, MERCHANT_ONE_ID, state="DISABLED")
    theirs = await _seed_coupon(database, MERCHANT_TWO_ID)

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/coupons")

    ids = {item["id"] for item in body["items"]}
    assert ids == {str(active)}
    assert not ids & {str(expired), str(future), str(disabled), str(theirs)}


@pytest.mark.asyncio
async def test_coupon_fields_follow_the_contract(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = _database(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    percent = await _seed_coupon(
        database,
        MERCHANT_ONE_ID,
        name="九折",
        kind="DISCOUNT",
        threshold_amount=None,
        discount_amount=None,
        discount_rate=Decimal("0.10"),
        scope="PRODUCTS",
        product_ids=[str(product)],
    )

    body = await _ok(postgres_client, f"/api/v2/shop/stores/{SHOP}/coupons")

    item = next(entry for entry in body["items"] if entry["id"] == str(percent))
    assert item["kind"] == "PERCENT_OFF"
    assert item["min_spend_cents"] == 0
    assert item["amount_off_cents"] is None
    assert item["discount_bps"] == 9000
    assert item["product_ids"] == [str(product)]
