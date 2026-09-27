"""顾客会话与公开目录的传输边界，不访问数据库或模型。"""

import pytest
from pydantic import ValidationError

from app.schemas.v2.shop_session import (
    CouponSummary,
    DemoCustomerBindRequest,
    DemoCustomerBindResponse,
    ProductDetailResponse,
    ProductSummary,
    ShopAnswerMode,
    ShopChatRequest,
    ShopChatResponse,
    ShopSessionCreateRequest,
    ShopSessionCreateResponse,
)


@pytest.mark.parametrize("field", ["merchant_id", "buyer_key", "session_id"])
def test_session_request_rejects_identity_overrides(field: str) -> None:
    with pytest.raises(ValidationError):
        ShopSessionCreateRequest.model_validate({"shop_slug": "borough-100", field: "fake"})


@pytest.mark.parametrize("slug", ["", "../store", "a/b", "A", "a--b", "a" * 65])
def test_invalid_shop_slug(slug: str) -> None:
    with pytest.raises(ValidationError):
        ShopSessionCreateRequest(shop_slug=slug)


def test_session_response_only_exposes_credential_and_role() -> None:
    assert set(ShopSessionCreateResponse.model_fields) == {"session_id", "role", "expires_at"}
    with pytest.raises(ValidationError):
        ShopSessionCreateResponse.model_validate(
            {"session_id": "uuid", "role": "CUSTOMER", "expires_at": "2026-09-21T00:00:00Z"}
        )


def test_bind_response_reports_cart_adjustment() -> None:
    """合并截顶或剔除不可售商品时必须让顾客知道（2026-09-21 裁定，E9）。"""
    base = {"role": "CUSTOMER", "is_bound": True, "expires_at": "2026-09-22T00:00:00+08:00"}
    assert DemoCustomerBindResponse.model_validate({**base, "cart_adjusted": True}).cart_adjusted
    with pytest.raises(ValidationError):
        DemoCustomerBindResponse.model_validate(base)
    with pytest.raises(ValidationError):
        DemoCustomerBindResponse.model_validate({**base, "cart_adjusted": "false"})


def test_bind_accepts_only_empty_body() -> None:
    assert DemoCustomerBindRequest().model_dump() == {}
    with pytest.raises(ValidationError):
        DemoCustomerBindRequest.model_validate({"buyer_key": "another-buyer"})


@pytest.mark.parametrize("field", ["session_id", "attachment_ids", "merchant_id", "buyer_key"])
def test_chat_rejects_untrusted_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        ShopChatRequest.model_validate({"message": "你好", "client_request_id": "r1", field: []})


def test_chat_requires_idempotency_and_defaults_new_conversation() -> None:
    with pytest.raises(ValidationError):
        ShopChatRequest.model_validate({"message": "你好"})
    request = ShopChatRequest(message="  你好  ", client_request_id="r1")
    assert request.conversation_id is None
    assert request.message == "你好"
    with pytest.raises(ValidationError):
        ShopChatRequest(message="  ", client_request_id="r1")
    assert "ATTACHMENT" not in {item.value for item in ShopAnswerMode}


def product(**changes: object) -> dict[str, object]:
    return {
        "id": "p1",
        "name": "商品",
        "short_description": "",
        "price_cents": 100,
        "stock_band": "IN_STOCK",
        "image_url": None,
        "source_locale": "zh-CN",
        "content_version": 1,
        "requested_locale": "zh-CN",
        "name_translation_status": "SOURCE",
        "short_description_translation_status": "SOURCE",
        **changes,
    }


@pytest.mark.parametrize("field", ["stock", "stock_on_hand", "stock_reserved", "stock_available"])
def test_product_rejects_exact_inventory(field: str) -> None:
    with pytest.raises(ValidationError):
        ProductSummary.model_validate(product(**{field: 10}))


@pytest.mark.parametrize("price", [1.2, True, -1])
def test_product_money_is_strict_integer(price: object) -> None:
    with pytest.raises(ValidationError):
        ProductSummary.model_validate(product(price_cents=price))


@pytest.mark.parametrize(
    "url",
    [
        "http://images.example.com/p.png",
        "//evil.test/p.png",
        "/demo/products/../secret",
        "/demo/products/%2e%2e/secret",
        "/demo/products/p.png?q=x",
        "https://images.example.com@evil.test/p.png",
        "https://127.0.0.1/p.png",
    ],
)
def test_unsafe_images_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        ProductSummary.model_validate(product(image_url=url))


def test_image_schema_is_context_free_and_host_allowlist_is_a_service_check() -> None:
    """依赖 validation context 会让 response_model 阶段拒绝所有外部图片。"""
    from app.schemas.v2.shop_session import is_trusted_image_host

    url = "https://images.example.com/p.png"
    assert ProductSummary.model_validate(product(image_url="/demo/products/p.png")).image_url
    assert ProductSummary.model_validate(product(image_url=url)).image_url == url
    assert is_trusted_image_host(url, {"images.example.com"})
    assert not is_trusted_image_host(url, set())
    assert not is_trusted_image_host("https://evil.test/p.png", {"images.example.com"})
    assert is_trusted_image_host("/demo/products/p.png", set())


@pytest.mark.parametrize(
    "url",
    [
        "http://images.example.com/p.png",
        "https://images.example.com:8080/p.png",
        "/demo/products/../secret",
        "/demo/products/%2e%2e/secret",
    ],
)
def test_image_host_allowlist_rejects_structurally_unsafe_urls(url: str) -> None:
    from app.schemas.v2.shop_session import is_trusted_image_host

    assert not is_trusted_image_host(url, {"images.example.com"})


def test_product_detail_requires_version_and_rejects_duplicate_attributes() -> None:
    data = product(
        description="", attributes=[], content_version=1, description_translation_status="SOURCE"
    )
    assert ProductDetailResponse.model_validate(data).content_version == 1
    attr = {
        "name": "颜色",
        "value": "蓝色",
        "source": "DEMO",
        "updated_at": "2026-09-21T08:00:00+08:00",
        "name_translation_status": "SOURCE",
        "value_translation_status": "SOURCE",
    }
    with pytest.raises(ValidationError):
        ProductDetailResponse.model_validate({**data, "attributes": [attr, attr]})


def test_coupon_kind_and_validity_are_consistent() -> None:
    data = {
        "id": "c1",
        "name": "优惠",
        "kind": "AMOUNT_OFF",
        "min_spend_cents": 200,
        "amount_off_cents": 100,
        "discount_bps": None,
        "product_ids": [],
        "starts_at": "2026-09-21T00:00:00Z",
        "ends_at": "2026-09-22T00:00:00Z",
    }
    assert CouponSummary.model_validate(data).amount_off_cents == 100
    for changes in [
        {"discount_bps": 9000},
        {"ends_at": data["starts_at"]},
        {"kind": "PERCENT_OFF"},
    ]:
        with pytest.raises(ValidationError):
            CouponSummary.model_validate({**data, **changes})


def test_chat_response_has_no_session_and_enforces_none_source() -> None:
    assert "session_id" not in ShopChatResponse.model_fields
    data = {
        "id": "a1",
        "conversation_id": "c1",
        "answer": "你好",
        "answer_mode": "CHAT",
        "analysis_sources": [{"source": "NONE", "degraded": False, "degraded_reason": None}],
        "quality_status": "NOT_RUN",
        "quality_attempts": 0,
        "degraded": False,
        "degraded_reason": None,
        "tool_calls": [],
        "created_at": "2026-09-21T00:00:00Z",
    }
    assert ShopChatResponse.model_validate(data).answer == "你好"
    for sources in [[], [{"source": "DATABASE", "degraded": False, "degraded_reason": None}]]:
        with pytest.raises(ValidationError):
            ShopChatResponse.model_validate({**data, "analysis_sources": sources})
