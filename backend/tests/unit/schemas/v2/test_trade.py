"""购物车、订单与履约事件的传输边界，不访问数据库。"""

import pytest
from pydantic import ValidationError

from app.schemas.v2.trade import (
    CartItem,
    CartItemSetRequest,
    CartResponse,
    FulfillmentEvent,
    FulfillmentEventPage,
    FulfillmentStatus,
    IllegalTransitionDetail,
    OrderCancelRequest,
    OrderCreateRequest,
    OrderDetailResponse,
    OrderItemPriceSnapshot,
    OrderPayRequest,
    OrderSummary,
    PaymentStatus,
)

NOW = "2026-09-21T00:00:00Z"


def cart_item(**changes: object) -> dict[str, object]:
    return {
        "product_id": "p1",
        "name": "商品",
        "image_url": None,
        "quantity": 2,
        "unit_price_cents": 500,
        "line_total_cents": 1000,
        "stock_band": "IN_STOCK",
        **changes,
    }


def order_item(**changes: object) -> dict[str, object]:
    return {
        "order_item_id": "oi1",
        "product_id": "p1",
        "name": "商品",
        "quantity": 2,
        "unit_price_cents": 500,
        "discount_cents": 100,
        "line_total_cents": 900,
        **changes,
    }


def order(**changes: object) -> dict[str, object]:
    return {
        "id": "o1",
        "payment_status": "PENDING",
        "fulfillment_status": "NOT_SHIPPED",
        "after_sale_status": "NONE",
        "total_cents": 900,
        "item_count": 2,
        "created_at": NOW,
        "pay_by": "2026-09-21T00:30:00Z",
        "items": [order_item()],
        "subtotal_cents": 1000,
        "discount_cents": 100,
        "coupon_id": None,
        "paid_at": None,
        "closed_at": None,
        "close_reason": None,
        "is_demo": True,
        **changes,
    }


def test_payment_and_fulfillment_are_separate_enums() -> None:
    assert {s.value for s in PaymentStatus} == {"PENDING", "PAID", "CLOSED"}
    assert {s.value for s in FulfillmentStatus} == {
        "NOT_SHIPPED",
        "SHIPPED",
        "IN_TRANSIT",
        "OUT_FOR_DELIVERY",
        "DELIVERED",
    }
    assert not ({s.value for s in PaymentStatus} & {s.value for s in FulfillmentStatus})


def test_cart_item_set_request_has_no_idempotency_key() -> None:
    assert "client_request_id" not in CartItemSetRequest.model_fields
    assert CartItemSetRequest(quantity=0).quantity == 0
    for bad in [-1, 100, 1.5, True]:
        with pytest.raises(ValidationError):
            CartItemSetRequest.model_validate({"quantity": bad})
    with pytest.raises(ValidationError):
        CartItemSetRequest.model_validate({"quantity": 1, "client_request_id": "r1"})


def test_customer_trade_contract_exposes_stock_band_not_quantities() -> None:
    forbidden = {"stock_on_hand", "stock_reserved", "stock_available", "stock"}
    assert "stock_band" in CartItem.model_fields
    assert not forbidden & set(CartItem.model_fields)
    with pytest.raises(ValidationError):
        CartItem.model_validate(cart_item(stock_available=99))
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"client_request_id": "r1", "stock_available": 99})


@pytest.mark.parametrize(
    "field", ["merchant_id", "buyer_key", "items", "total_cents", "unit_price"]
)
def test_order_create_rejects_client_supplied_amounts_and_identity(field: str) -> None:
    with pytest.raises(ValidationError):
        OrderCreateRequest.model_validate({"client_request_id": "r1", field: 1})
    assert OrderCreateRequest(client_request_id="r1").coupon_id is None


def test_write_requests_require_client_request_id() -> None:
    for model in (OrderCreateRequest, OrderPayRequest, OrderCancelRequest):
        with pytest.raises(ValidationError):
            model.model_validate({})
        assert model(client_request_id="r1")


def test_cart_totals_are_consistent_and_deduplicated() -> None:
    item = cart_item()
    assert CartResponse.model_validate({"items": [item], "subtotal_cents": 1000})
    with pytest.raises(ValidationError):
        CartResponse.model_validate({"items": [item], "subtotal_cents": 999})
    with pytest.raises(ValidationError):
        CartResponse.model_validate({"items": [item, item], "subtotal_cents": 2000})
    with pytest.raises(ValidationError):
        CartItem.model_validate(cart_item(line_total_cents=1))
    with pytest.raises(ValidationError):
        CartResponse.model_validate(
            {
                "items": [cart_item(product_id=f"p{i}") for i in range(51)],
                "subtotal_cents": 51000,
            }
        )


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "http://images.example.com/p.png", "/demo/products/../secret"],
)
def test_cart_image_uses_public_product_url_rules(url: str) -> None:
    with pytest.raises(ValidationError):
        CartItem.model_validate(cart_item(image_url=url))


def test_order_item_carries_full_price_snapshot() -> None:
    assert {"unit_price_cents", "discount_cents", "line_total_cents"} <= set(
        OrderItemPriceSnapshot.model_fields
    )
    assert OrderItemPriceSnapshot.model_validate(order_item()).line_total_cents == 900
    for changes in [{"line_total_cents": 901}, {"discount_cents": 1001, "line_total_cents": 0}]:
        with pytest.raises(ValidationError):
            OrderItemPriceSnapshot.model_validate(order_item(**changes))


def test_order_detail_exposes_projections_but_events_use_separate_page() -> None:
    fields = OrderDetailResponse.model_fields
    assert {"payment_status", "fulfillment_status", "after_sale_status"} <= set(fields)
    assert "events" not in fields
    assert "items" in FulfillmentEventPage.model_fields
    assert OrderDetailResponse.model_validate(order()).total_cents == 900


@pytest.mark.parametrize(
    "changes",
    [
        {"total_cents": 1000},
        {"subtotal_cents": 999},
        {"discount_cents": 0},
        {"item_count": 3},
        {"items": [order_item(), order_item()], "item_count": 4},
        {"paid_at": NOW},
        {"payment_status": "PAID"},
        {"payment_status": "CLOSED", "closed_at": NOW},
        {"closed_at": NOW, "close_reason": "USER_CANCELLED"},
        {"is_demo": False},
        {"pay_by": "2026-09-20T23:59:59Z"},
    ],
)
def test_order_detail_rejects_inconsistent_states(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OrderDetailResponse.model_validate(order(**changes))


def test_paid_and_closed_orders_carry_their_timestamps() -> None:
    paid = order(payment_status="PAID", paid_at=NOW, fulfillment_status="SHIPPED")
    assert OrderDetailResponse.model_validate(paid).paid_at is not None
    closed = order(payment_status="CLOSED", closed_at=NOW, close_reason="PAYMENT_TIMEOUT")
    assert OrderDetailResponse.model_validate(closed).close_reason == "PAYMENT_TIMEOUT"


def test_unpaid_order_cannot_be_shipped() -> None:
    summary = {
        "id": "o1",
        "payment_status": "PENDING",
        "fulfillment_status": "SHIPPED",
        "after_sale_status": "NONE",
        "total_cents": 1,
        "item_count": 1,
        "created_at": NOW,
        "pay_by": NOW,
    }
    with pytest.raises(ValidationError):
        OrderSummary.model_validate(summary)


def test_event_page_is_cursor_page_and_records_source_timezone() -> None:
    event = {
        "id": "e1",
        "event_type": "ORDER_PLACED",
        "occurred_at": "2026-09-21T08:00:00+08:00",
        "source_timezone": "Asia/Shanghai",
    }
    page = FulfillmentEventPage.model_validate(
        {"items": [event], "next_cursor": None, "has_more": False}
    )
    assert page.items[0].occurred_at.isoformat() == "2026-09-21T00:00:00+00:00"
    with pytest.raises(ValidationError):
        FulfillmentEvent.model_validate({**event, "source_timezone": ""})
    with pytest.raises(ValidationError):
        FulfillmentEvent.model_validate({**event, "occurred_at": "2026-09-21T08:00:00"})
    with pytest.raises(ValidationError):
        FulfillmentEvent.model_validate({**event, "event_type": "REFUNDED"})


def test_illegal_transition_detail_only_leaks_payment_status() -> None:
    assert set(IllegalTransitionDetail.model_fields) == {"payment_status"}
    with pytest.raises(ValidationError):
        IllegalTransitionDetail.model_validate({"payment_status": "PAID", "lock_owner": "x"})
