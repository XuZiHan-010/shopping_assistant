"""v2 路由的 OpenAPI 哨兵（始于 §8.0.1 门槛 5 的 N1 5 条会话签发路由）。

方法、鉴权头、请求/响应模型名和错误码任何一项漂移，前端生成类型与各端 Adapter
都会跟着错，所以在这里逐条钉死；新增 v2 路由落地时同步登记，不放宽约束。字段本身以
`docs/backend-development-plan.md` §8.8.2 / §8.9.2 / §8.14.4 为准，本文件不复写字段清单。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.export_openapi import export_settings  # noqa: E402

SHOP_SESSIONS = "/api/v2/shop/sessions"
SHOP_DEMO_CUSTOMER = "/api/v2/shop/sessions/demo-customer"
SHOP_CURRENT = "/api/v2/shop/sessions/current"
MERCHANT_SESSIONS = "/api/v2/merchant/sessions"
MERCHANT_CURRENT = "/api/v2/merchant/sessions/current"
#: N2 模块 D（会话目录与反馈）率先落地的第一条 v2 业务路由，不受本文件标题的
#: "N1 会话签发" 范围约束，但复用同一套 OpenAPI 哨兵防止字段/错误码漂移。
MERCHANT_FEEDBACK = "/api/v2/merchant/answers/{answer_id}/feedback"
#: N2 模块 C（草稿审批与库存运营）落地的 5 条商家路由。
MERCHANT_ALERTS = "/api/v2/merchant/inventory/alerts"
MERCHANT_PRODUCTS_CONTENT = "/api/v2/merchant/products/content"
MERCHANT_COUPONS = "/api/v2/merchant/coupons"
MERCHANT_DRAFTS = "/api/v2/merchant/drafts"
MERCHANT_DRAFT = "/api/v2/merchant/drafts/{draft_id}"
MERCHANT_DRAFT_APPLY = "/api/v2/merchant/drafts/{draft_id}/apply"
MERCHANT_BRIEF = "/api/v2/merchant/briefs/daily/current"
#: N3 阶段 C Task 2（完整每日简报限流重新生成）。
MERCHANT_BRIEF_REGENERATE = "/api/v2/merchant/briefs/daily/current/regenerate"
MERCHANT_CHAT = "/api/v2/merchant/chat"
#: N2 模块 B Task 1（顾客端公开浏览）落地的 4 条公开路由。
SHOP_STORE = "/api/v2/shop/stores/{shop_slug}"
SHOP_PRODUCTS = "/api/v2/shop/stores/{shop_slug}/products"
SHOP_PRODUCT = "/api/v2/shop/stores/{shop_slug}/products/{product_id}"
SHOP_COUPONS = "/api/v2/shop/stores/{shop_slug}/coupons"
#: N2 模块 B Task 2（购物车）落地的 3 条顾客会话路由；PUT/DELETE 天然幂等，不带 client_request_id。
SHOP_CART = "/api/v2/shop/cart"
SHOP_CART_ITEM = "/api/v2/shop/cart/items/{product_id}"
#: N2 模块 B Task 3–5（订单）：下单、支付、取消携带 client_request_id（§8.7.3）。
SHOP_ORDERS = "/api/v2/shop/orders"
SHOP_ORDER = "/api/v2/shop/orders/{order_id}"
SHOP_ORDER_EVENTS = "/api/v2/shop/orders/{order_id}/events"
SHOP_ORDER_PAY = "/api/v2/shop/orders/{order_id}/pay"
SHOP_ORDER_CANCEL = "/api/v2/shop/orders/{order_id}/cancel"
#: N2 模块 B Task 6（顾客导购 Chat），默认 SSE。
SHOP_CHAT = "/api/v2/shop/chat"
#: N2 模块 D Task 1（双端会话目录）。
SHOP_CONVERSATIONS = "/api/v2/shop/conversations"
SHOP_CONVERSATION = "/api/v2/shop/conversations/{conversation_id}"
MERCHANT_CONVERSATIONS = "/api/v2/merchant/conversations"
MERCHANT_CONVERSATION = "/api/v2/merchant/conversations/{conversation_id}"
# N3 阶段 B：顾客售后四条、商家售后两条、顾客信号两条。
SHOP_AFTER_SALES = "/api/v2/shop/after-sales"
SHOP_AFTER_SALE = "/api/v2/shop/after-sales/{after_sale_id}"
SHOP_AFTER_SALE_SUPPLEMENTS = "/api/v2/shop/after-sales/{after_sale_id}/supplements"
MERCHANT_AFTER_SALES = "/api/v2/merchant/after-sales"
MERCHANT_AFTER_SALE = "/api/v2/merchant/after-sales/{after_sale_id}"
MERCHANT_SIGNALS = "/api/v2/merchant/customer-signals"
MERCHANT_SIGNAL_IGNORE = "/api/v2/merchant/customer-signals/{signal_id}/ignore"
# N4 B：双端记忆 5 条。内部身份从会话解析，不在请求字段暴露。
SHOP_MEMORIES = "/api/v2/shop/memories"
SHOP_MEMORY = "/api/v2/shop/memories/{memory_id}"
SHOP_MEMORY_PREFERENCE = "/api/v2/shop/memory-preference"
MERCHANT_MEMORIES = "/api/v2/merchant/memories"
MERCHANT_MEMORY = "/api/v2/merchant/memories/{memory_id}"
#: W 阶段 Task 2：首页经营主指标（§8.12.4）。周期由后端固定，不接受任何查询参数。
MERCHANT_METRICS_OVERVIEW = "/api/v2/merchant/metrics/overview"
#: W 阶段 Task 3：商家订单只读面（§8.12.4）。仅本店具备 v2 交易投影的订单。
MERCHANT_ORDERS = "/api/v2/merchant/orders"
#: N5 A：MCP 只读入口（§8.14.3）。鉴权与正文都不按普通 v2 路由的形状：只认 MCP Bearer、
#: 正文是 SDK 协议类型的 JSON-RPC，所以不进 `EXPECTED` 的逐条模型断言，由下方专用哨兵固定。
MERCHANT_MCP = "/api/v2/merchant/mcp"
MERCHANT_ORDER = "/api/v2/merchant/orders/{order_id}"

# (方法, 路径) → (鉴权类别, 成功状态码, 请求模型, 响应模型, 声明的错误码)
# 鉴权类别对应 AGENTS.md §8.3：public / bearer / session。
EXPECTED: dict[tuple[str, str], tuple[str, str, str | None, str | None, set[str]]] = {
    ("post", SHOP_SESSIONS): (
        "public",
        "201",
        "ShopSessionCreateRequest",
        "ShopSessionCreateResponse",
        {"403", "422", "429", "503"},
    ),
    ("post", SHOP_DEMO_CUSTOMER): (
        "session",
        "200",
        "DemoCustomerBindRequest",
        "DemoCustomerBindResponse",
        {"401", "403", "404", "409", "422", "503"},
    ),
    ("delete", SHOP_CURRENT): ("session", "204", None, None, {"401", "403", "422", "503"}),
    ("post", MERCHANT_SESSIONS): (
        "bearer",
        "201",
        "MerchantSessionCreateRequest",
        "MerchantSessionCreateResponse",
        {"401", "422", "429", "503"},
    ),
    ("delete", MERCHANT_CURRENT): ("session", "204", None, None, {"401", "403", "422", "503"}),
    ("post", MERCHANT_FEEDBACK): (
        "session",
        "200",
        "V2FeedbackRequest",
        "V2FeedbackResponse",
        {"401", "403", "409", "422", "503"},
    ),
    ("get", MERCHANT_ALERTS): (
        "session",
        "200",
        None,
        "CursorPage_InventoryAlert_",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_PRODUCTS_CONTENT): (
        "session", "200", None, "CursorPage_MerchantProductContent_",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_COUPONS): (
        "session", "200", None, "CursorPage_MerchantCoupon_",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_DRAFTS): (
        "session",
        "200",
        None,
        "CursorPage_DraftSummary_",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_DRAFT): (
        "session",
        "200",
        None,
        "DraftDetailResponse",
        {"401", "403", "422", "503"},
    ),
    ("post", MERCHANT_DRAFT_APPLY): (
        "session",
        "200",
        "DraftApplyRequest",
        "DraftApplyResponse",
        {"401", "403", "409", "422", "503"},
    ),
    ("delete", MERCHANT_DRAFT): ("session", "204", None, None, {"401", "403", "409", "422", "503"}),
    ("get", MERCHANT_BRIEF): (
        "session",
        "200",
        None,
        "DailyBriefResponse",
        # 2026-09-26 修正：不返回 404——尚无已存储简报时现算并落为第 1 版再返回
        # （定时任务默认关闭，严格 404 会让商家在首次手动重新生成前永远看不到简报）；
        # 422 保留声明以覆盖 FastAPI 默认注入的校验错误响应结构（即使本端点当前
        # 无查询参数或请求体，未声明会导致 422 走 FastAPI 自己的 HTTPValidationError
        # 而不是我们的 ErrorResponse，见 `error_responses()` 的文档字符串）。
        {"401", "403", "422", "503"},
    ),
    ("post", MERCHANT_BRIEF_REGENERATE): (
        "session",
        "200",
        "BriefRegenerateRequest",
        "DailyBriefResponse",
        {"401", "403", "409", "422", "429", "503"},
    ),
    ("post", MERCHANT_CHAT): (
        "session",
        "200",
        "MerchantChatRequest",
        "MerchantChatResponse",
        {"401", "403", "409", "422", "429", "503"},
    ),
    ("get", SHOP_STORE): ("public", "200", None, "StoreProfileResponse", {"403", "422", "503"}),
    ("get", SHOP_PRODUCTS): (
        "public",
        "200",
        None,
        "CursorPage_ProductSummary_",
        {"403", "422", "503"},
    ),
    ("get", SHOP_PRODUCT): ("public", "200", None, "ProductDetailResponse", {"403", "422", "503"}),
    ("get", SHOP_COUPONS): (
        "public",
        "200",
        None,
        "CursorPage_CouponSummary_",
        {"403", "422", "503"},
    ),
    ("get", SHOP_CART): ("session", "200", None, "CartResponse", {"401", "403", "422", "503"}),
    ("put", SHOP_CART_ITEM): (
        "session",
        "200",
        "CartItemSetRequest",
        "CartResponse",
        {"401", "403", "409", "422", "503"},
    ),
    ("delete", SHOP_CART_ITEM): (
        "session",
        "200",
        None,
        "CartResponse",
        {"401", "403", "422", "503"},
    ),
    ("post", SHOP_ORDERS): (
        "session",
        "201",
        "OrderCreateRequest",
        "OrderDetailResponse",
        {"401", "403", "409", "422", "503"},
    ),
    ("get", SHOP_ORDERS): (
        "session",
        "200",
        None,
        "CursorPage_OrderSummary_",
        {"401", "403", "422", "503"},
    ),
    ("get", SHOP_ORDER): (
        "session",
        "200",
        None,
        "OrderDetailResponse",
        {"401", "403", "422", "503"},
    ),
    ("get", SHOP_ORDER_EVENTS): (
        "session",
        "200",
        None,
        "FulfillmentEventPage",
        {"401", "403", "422", "503"},
    ),
    ("post", SHOP_ORDER_PAY): (
        "session",
        "200",
        "OrderPayRequest",
        "OrderDetailResponse",
        {"401", "403", "409", "422", "503"},
    ),
    ("post", SHOP_ORDER_CANCEL): (
        "session",
        "200",
        "OrderCancelRequest",
        "OrderDetailResponse",
        {"401", "403", "409", "422", "503"},
    ),
    ("post", SHOP_CHAT): (
        "session",
        "200",
        "ShopChatRequest",
        "ShopChatResponse",
        {"401", "403", "409", "422", "429", "503"},
    ),
    ("get", SHOP_CONVERSATIONS): (
        "session",
        "200",
        None,
        "CursorPage_ShopConversationSummary_",
        {"401", "403", "422", "503"},
    ),
    ("get", SHOP_CONVERSATION): (
        "session",
        "200",
        None,
        "ShopConversationDetailResponse",
        {"401", "403", "422", "503"},
    ),
    ("delete", SHOP_CONVERSATION): ("session", "204", None, None, {"401", "403", "422", "503"}),
    ("get", MERCHANT_CONVERSATIONS): (
        "session",
        "200",
        None,
        "CursorPage_MerchantConversationSummary_",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_CONVERSATION): (
        "session",
        "200",
        None,
        "MerchantConversationDetailResponse",
        {"401", "403", "422", "503"},
    ),
    ("delete", MERCHANT_CONVERSATION): (
        "session",
        "204",
        None,
        None,
        {"401", "403", "422", "503"},
    ),
    ("post", SHOP_AFTER_SALES): (
        "session", "200", "AfterSaleCreateRequest", "AfterSaleConfirmationChallenge",
        {"401", "403", "409", "422", "503"},
    ),
    ("get", SHOP_AFTER_SALES): (
        "session", "200", None, "CursorPage_AfterSaleSummary_",
        {"401", "403", "422", "503"},
    ),
    ("get", SHOP_AFTER_SALE): (
        "session", "200", None, "CustomerAfterSaleDetailResponse",
        {"401", "403", "422", "503"},
    ),
    ("post", SHOP_AFTER_SALE_SUPPLEMENTS): (
        "session", "200", "AfterSaleSupplementRequest", "AfterSaleSummary",
        {"401", "403", "409", "422", "503"},
    ),
    ("get", MERCHANT_AFTER_SALES): (
        "session", "200", None, "CursorPage_MerchantAfterSaleSummary_",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_AFTER_SALE): (
        "session", "200", None, "MerchantAfterSaleDetailResponse",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_SIGNALS): (
        "session", "200", None, "CursorPage_CustomerSignal_",
        {"401", "403", "422", "503"},
    ),
    ("post", MERCHANT_SIGNAL_IGNORE): (
        "session", "200", "SignalIgnoreRequest", "CustomerSignal",
        {"401", "403", "409", "422", "503"},
    ),
    ("get", SHOP_MEMORIES): (
        "session", "200", None, "CustomerMemoriesResponse",
        {"401", "403", "422", "503"},
    ),
    ("delete", SHOP_MEMORY): (
        "session", "204", None, None, {"401", "403", "422", "503"},
    ),
    ("put", SHOP_MEMORY_PREFERENCE): (
        "session", "200", "MemoryPreferenceRequest", "MemoryPreferenceResponse",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_MEMORIES): (
        "session", "200", None, "MerchantMemoriesResponse",
        {"401", "403", "422", "503"},
    ),
    ("delete", MERCHANT_MEMORY): (
        "session", "200", None, "MerchantMemoryDeleteResponse",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_METRICS_OVERVIEW): (
        "session", "200", None, "MerchantMetricsOverviewResponse",
        # 422 同当日简报：覆盖 FastAPI 默认注入的校验错误响应结构。
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_ORDERS): (
        "session", "200", None, "CursorPage_MerchantOrderSummary_",
        {"401", "403", "422", "503"},
    ),
    ("get", MERCHANT_ORDER): (
        "session", "200", None, "MerchantOrderDetailResponse",
        {"401", "403", "422", "503"},
    ),
}

# 两阶段创建的第二个成功分支，状态码和模型都单独固定。
EXTRA_SUCCESS: dict[tuple[str, str], tuple[str, str]] = {
    ("post", SHOP_AFTER_SALES): ("201", "AfterSaleSummary"),
}

#: 允许出现的查询参数，逐条登记。分页与筛选是契约 §8.7.4 / §8.12.3 / §8.13.3 要求的；
#: 身份类参数一个都不许有——身份只从会话解析（R5）。
QUERY_PARAMS: dict[tuple[str, str], set[str]] = {
    ("get", MERCHANT_ALERTS): {"cursor", "limit", "kind"},
    ("get", MERCHANT_PRODUCTS_CONTENT): {"cursor", "limit"},
    ("get", MERCHANT_COUPONS): {"cursor", "limit"},
    ("get", MERCHANT_DRAFTS): {"cursor", "limit", "state", "kind", "batch_id"},
    ("get", SHOP_PRODUCTS): {"cursor", "limit", "sort"},
    ("get", SHOP_COUPONS): {"cursor", "limit"},
    ("get", SHOP_ORDERS): {"cursor", "limit"},
    ("get", SHOP_ORDER_EVENTS): {"cursor", "limit"},
    ("get", SHOP_CONVERSATIONS): {"cursor", "limit"},
    ("get", SHOP_CONVERSATION): {"cursor", "limit"},
    ("get", MERCHANT_CONVERSATIONS): {"cursor", "limit"},
    ("get", MERCHANT_CONVERSATION): {"cursor", "limit"},
    ("get", SHOP_AFTER_SALES): {"cursor", "limit"},
    ("get", MERCHANT_AFTER_SALES): {"cursor", "limit", "state"},
    ("get", MERCHANT_SIGNALS): {"cursor", "limit", "include_ignored"},
    ("get", SHOP_MEMORIES): {"cursor", "limit"},
    ("get", MERCHANT_MEMORIES): {"cursor", "limit"},
    ("get", MERCHANT_ORDERS): {
        "cursor", "limit", "payment_status", "fulfillment_status", "after_sale_status",
    },
}

#: 任何路由都不得以查询参数接受这些名字。
FORBIDDEN_QUERY_PARAMS = {"merchant_id", "buyer_key", "session_id", "shop_slug", "admin_token"}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    app: FastAPI = create_app(export_settings())
    return app.openapi()


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def test_v2_exposes_exactly_the_registered_paths(schema: dict[str, Any]) -> None:
    """未登记在 `EXPECTED` 里的 v2 路径提前出现，说明有路由绕过了 §8.0.1 前置条件。

    N1 只落地 5 条会话签发路由；N2 模块 D（会话目录与反馈）之后逐条新增业务路由时，
    必须同时在本文件的 `EXPECTED` 里登记，而不是让这条哨兵失效或被放宽成无约束。
    """

    v2_paths = {path for path in schema["paths"] if path.startswith("/api/v2/")}

    assert v2_paths == {path for _, path in EXPECTED} | {MERCHANT_MCP}
    assert set(schema["paths"][MERCHANT_MCP]) == {"post"}
    for path in v2_paths - {MERCHANT_MCP}:
        expected_methods = {method for method, p in EXPECTED if p == path}
        assert set(schema["paths"][path]) == expected_methods, path


@pytest.mark.parametrize(("method", "path"), list(EXPECTED))
def test_session_route_auth_headers_are_fixed(
    schema: dict[str, Any], method: str, path: str
) -> None:
    auth = EXPECTED[(method, path)][0]
    operation = schema["paths"][path][method]
    headers = {
        parameter["name"]
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "header"
    }
    # 会话身份只能来自服务端解析：查询参数必须在登记的分页/筛选白名单内，
    # 且永远不出现身份类名字（R5）。
    query = {p["name"] for p in operation.get("parameters", []) if p["in"] == "query"}
    assert query == QUERY_PARAMS.get((method, path), set()), path
    assert not (query & FORBIDDEN_QUERY_PARAMS), path

    if auth == "public":
        assert headers == set()
        assert "security" not in operation
    elif auth == "bearer":
        # 商家登录 Token 只走 Authorization，不接受 X-Session-Id。
        assert headers == set()
        assert operation["security"] == [{"HTTPBearer": []}]
    else:
        assert headers == {"X-Session-Id"}
        assert "security" not in operation


@pytest.mark.parametrize(("method", "path"), list(EXPECTED))
def test_session_route_models_and_status_codes_are_fixed(
    schema: dict[str, Any], method: str, path: str
) -> None:
    _, success, request_model, response_model, errors = EXPECTED[(method, path)]
    operation = schema["paths"][path][method]
    responses = operation["responses"]

    extra = EXTRA_SUCCESS.get((method, path))
    assert set(responses) == ({success} | errors | ({extra[0]} if extra else set()))
    if request_model is None:
        assert "requestBody" not in operation
    else:
        body = operation["requestBody"]["content"]["application/json"]["schema"]
        assert body == _ref(request_model)
    if response_model is None:
        assert "content" not in responses[success]
    else:
        assert responses[success]["content"]["application/json"]["schema"] == _ref(response_model)
    if extra:
        assert responses[extra[0]]["content"]["application/json"]["schema"] == _ref(extra[1])
    for code in errors:
        assert responses[code]["content"]["application/json"]["schema"] == _ref("ErrorResponse"), (
            f"{method.upper()} {path} 的 {code} 响应体不是 ErrorResponse"
        )


@pytest.mark.parametrize(
    "model",
    [
        "ShopSessionCreateRequest",
        "DemoCustomerBindRequest",
        "MerchantSessionCreateRequest",
    ],
)
def test_session_requests_reject_client_supplied_identity(
    schema: dict[str, Any], model: str
) -> None:
    """请求体不得出现 merchant_id / buyer_key，且多余字段一律拒绝（extra="forbid"）。"""

    component = schema["components"]["schemas"][model]

    assert component.get("additionalProperties") is False
    assert not {"merchant_id", "buyer_key"} & set(component.get("properties", {}))


@pytest.mark.parametrize("model", ["ProductSummary", "ProductDetailResponse", "CouponSummary"])
def test_public_catalog_models_expose_no_identity_or_stock_quantity(
    schema: dict[str, Any], model: str
) -> None:
    """D5：顾客端库存只有三档；公开模型里不得出现任何数量字段或租户标识。"""

    properties = set(schema["components"]["schemas"][model].get("properties", {}))

    assert not properties & {
        "merchant_id",
        "buyer_key",
        "stock_on_hand",
        "stock_reserved",
        "stock_available",
        "low_stock_threshold",
    }


def test_merchant_session_response_carries_shop_slug(schema: dict[str, Any]) -> None:
    """D-N5-4（契约 §8.9.1）：响应必带 `shop_slug`，格式与顾客端会话请求的同名字段一致。"""

    schemas = schema["components"]["schemas"]
    response = schemas["MerchantSessionCreateResponse"]
    assert "shop_slug" in response["required"]
    assert response["properties"]["shop_slug"] == (
        schemas["ShopSessionCreateRequest"]["properties"]["shop_slug"]
    )
    # 请求体仍为空对象：标识只从已验证会话解析，不接受传入。
    assert not schemas["MerchantSessionCreateRequest"].get("properties")


def test_mcp_route_contract_is_fixed(schema: dict[str, Any]) -> None:
    """MCP 入口：只 POST；不收 `X-Session-Id` 与任何查询参数；协议头三项登记在案（§8.14.3）。"""

    operation = schema["paths"][MERCHANT_MCP]["post"]
    parameters = operation.get("parameters", [])
    headers = {p["name"] for p in parameters if p["in"] == "header"}
    query = {p["name"] for p in parameters if p["in"] == "query"}

    assert headers == {"MCP-Protocol-Version", "Mcp-Method", "Mcp-Name"}
    assert query == set()
    assert set(operation["responses"]) == {"200", "202", "400", "401", "413", "429", "503"}
    assert "security" not in operation  # 不复用商家登录 Token 的 HTTPBearer 方案
