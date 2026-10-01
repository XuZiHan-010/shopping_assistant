"""每条校验拒绝语句都有独立用例。

由变异检验发现：把 `app/schemas/v2` 中某个 `raise ValueError` 删掉后，原有测试仍全绿，
说明那条校验没有被单独验证（常见原因是另一条校验恰好先拦下了同一个坏输入）。
这里用 `match=` 锁定具体是哪一条校验触发，防止它们互相掩护。
"""

import pytest
from pydantic import ValidationError

from app.schemas.v2.after_sales import (
    AfterSaleChallengeSummary,
    AfterSaleSummary,
    CustomerAfterSaleDetailResponse,
)
from app.schemas.v2.common import DegradationMixin, cents_to_yuan
from app.schemas.v2.merchant_ops import CustomerSignal, InventoryAlert
from app.schemas.v2.shop_session import CouponSummary, ProductSummary, ShopConversationMessage
from app.schemas.v2.trade import OrderDetailResponse, OrderItemPriceSnapshot

T0 = "2026-09-21T00:00:00Z"
T1 = "2026-09-21T01:00:00Z"


def product(**changes: object) -> dict[str, object]:
    return {
        "id": "p1",
        "name": "商品",
        "short_description": "",
        "price_cents": 100,
        "stock_band": "IN_STOCK",
        "image_url": None,
        **changes,
    }


def chat_answer(**changes: object) -> dict[str, object]:
    return {
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
        "created_at": T0,
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
        "created_at": T0,
        "pay_by": "2026-09-21T00:30:00Z",
        "lead_item": {"product_id": "p1", "name": "商品", "image_url": None},
        "last_event_at": T0,
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


def detail(**changes: object) -> dict[str, object]:
    events = [
        {
            "id": f"e{i}",
            "from_state": previous,
            "to_state": state,
            "actor": "CUSTOMER" if previous is None else "MERCHANT",
            "occurred_at": T0,
        }
        for i, (previous, state) in enumerate(
            [(None, "PENDING_MERCHANT"), ("PENDING_MERCHANT", "APPROVED")]
        )
    ]
    return {
        "id": "a1",
        "order_id": "o1",
        "after_sale_type": "REFUND_ONLY",
        "state": "APPROVED",
        "refund_amount_cents": 900,
        "created_at": T0,
        "updated_at": T1,
        "reason": "质量问题",
        "lines": [{"snapshot": order_item(), "refund_cents": 900}],
        "events": events,
        "supplements": [],
        "replies": [],
        "conversation_summary_shared": False,
        **changes,
    }


def alert(**changes: object) -> dict[str, object]:
    return {
        "id": "al1",
        "kind": "LOW_STOCK",
        "product_id": "p1",
        "product_name": "商品",
        "stock_on_hand": 10,
        "stock_reserved": 6,
        "stock_available": 4,
        "low_stock_threshold": 5,
        "sold_last_30d": 30,
        "days_of_supply": 4,
        **changes,
    }


@pytest.mark.parametrize("value", [True, -1, 99999999999999 + 1, 1.5, "100"])
def test_cents_to_yuan_rejects_non_integer_or_out_of_range_input(value: object) -> None:
    with pytest.raises(ValueError, match="整数分"):
        cents_to_yuan(value)  # type: ignore[arg-type]


def test_fallback_source_requires_the_whole_turn_to_be_degraded() -> None:
    """来源自身已降级，但整轮未降级：规则兜底不得被包装成正常回答。"""
    payload = {
        "analysis_sources": [
            {"source": "FALLBACK", "degraded": True, "degraded_reason": "规则兜底"}
        ],
        "quality_status": "DEGRADED",
        "quality_attempts": 0,
        "degraded": False,
        "degraded_reason": None,
    }
    with pytest.raises(ValidationError, match="整轮降级"):
        DegradationMixin.model_validate(payload)
    degraded = {**payload, "degraded": True, "degraded_reason": "规则兜底"}
    assert DegradationMixin.model_validate(degraded).degraded is True


@pytest.mark.parametrize(
    "url", ["/demo/products/a b.png", "/demo/products/a\nb.png", "/demo/products/a\\b.png"]
)
def test_image_url_rejects_whitespace_control_and_backslash(url: str) -> None:
    with pytest.raises(ValidationError, match="非法字符"):
        ProductSummary.model_validate(product(image_url=url))


def test_coupon_product_ids_must_be_unique() -> None:
    data = {
        "id": "c1",
        "name": "优惠",
        "kind": "AMOUNT_OFF",
        "min_spend_cents": 200,
        "amount_off_cents": 100,
        "discount_bps": None,
        "product_ids": ["p1", "p1"],
        "starts_at": T0,
        "ends_at": "2026-09-22T00:00:00Z",
    }
    with pytest.raises(ValidationError, match="优惠券商品不得重复"):
        CouponSummary.model_validate(data)


def test_history_message_answer_must_match_role_and_content() -> None:
    base = {"id": "m1", "created_at": T0}
    assert ShopConversationMessage.model_validate(
        {**base, "role": "user", "content": "你好", "answer": None}
    )
    assert ShopConversationMessage.model_validate(
        {**base, "role": "assistant", "content": "你好", "answer": chat_answer()}
    )
    with pytest.raises(ValidationError, match="顾客消息不得携带最终回答"):
        ShopConversationMessage.model_validate(
            {**base, "role": "user", "content": "你好", "answer": chat_answer()}
        )
    for content, answer in [("其他", chat_answer()), ("你好", None)]:
        with pytest.raises(ValidationError, match="助手消息必须与完整回答一致"):
            ShopConversationMessage.model_validate(
                {**base, "role": "assistant", "content": content, "answer": answer}
            )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"discount_cents": 1001, "line_total_cents": 0}, "行优惠不得超过行原价"),
        ({"line_total_cents": 901}, "行实付必须等于原价减优惠"),
    ],
)
def test_snapshot_guards_fire_individually(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        OrderItemPriceSnapshot.model_validate(order_item(**changes))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "items": [order_item(), order_item()],
                "subtotal_cents": 2000,
                "discount_cents": 200,
                "total_cents": 1800,
                "item_count": 4,
            },
            "订单行不得重复",
        ),
        ({"subtotal_cents": 999}, "订单原价与优惠必须等于各行之和"),
        ({"discount_cents": 0}, "订单原价与优惠必须等于各行之和"),
        ({"total_cents": 1000}, "订单应付必须等于各行实付之和"),
        ({"item_count": 3}, "件数必须等于各行数量之和"),
        ({"paid_at": T0}, "支付时间仅在已支付订单出现"),
        ({"payment_status": "CLOSED", "closed_at": T0}, "关闭时间与原因仅在已关闭订单成对出现"),
        (
            {"closed_at": T0, "close_reason": "USER_CANCELLED"},
            "关闭时间与原因仅在已关闭订单成对出现",
        ),
    ],
)
def test_order_detail_guards_fire_individually(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        OrderDetailResponse.model_validate(order(**changes))


def test_challenge_summary_shows_conversation_text_only_when_included() -> None:
    base = {
        "order_id": "o1",
        "after_sale_type": "REFUND_ONLY",
        "lines": [],
        "estimated_refund_cents": 900,
        "reason": "",
    }
    included = {**base, "conversation_summary_status": "INCLUDED", "conversation_summary": "摘要"}
    assert AfterSaleChallengeSummary.model_validate(included)
    for status, text in [("INCLUDED", None), ("NOT_SHARED", "泄露"), ("UNAVAILABLE", "泄露")]:
        with pytest.raises(ValidationError, match="对话摘要仅在已包含时出现"):
            AfterSaleChallengeSummary.model_validate(
                {**base, "conversation_summary_status": status, "conversation_summary": text}
            )


def test_after_sale_summary_rejects_update_before_creation() -> None:
    payload = {
        "id": "a1",
        "order_id": "o1",
        "after_sale_type": "REFUND_ONLY",
        "state": "APPROVED",
        "refund_amount_cents": 900,
        "created_at": T1,
        "updated_at": T0,
    }
    with pytest.raises(ValidationError, match="更新时间不得早于创建时间"):
        AfterSaleSummary.model_validate(payload)


def test_after_sale_detail_line_guards_fire_individually() -> None:
    line = {"snapshot": order_item(), "refund_cents": 900}
    with pytest.raises(ValidationError, match="售后行不得重复"):
        CustomerAfterSaleDetailResponse.model_validate(
            detail(lines=[line, line], refund_amount_cents=1800)
        )
    with pytest.raises(ValidationError, match="退款类售后必须包含订单行"):
        CustomerAfterSaleDetailResponse.model_validate(detail(lines=[], refund_amount_cents=0))
    with pytest.raises(ValidationError, match="退款合计必须等于各行退款之和"):
        CustomerAfterSaleDetailResponse.model_validate(detail(refund_amount_cents=100))
    ticket = {
        "after_sale_type": "TICKET",
        "refund_amount_cents": None,
        "lines": [{"snapshot": order_item(), "refund_cents": 100}],
    }
    with pytest.raises(ValidationError, match="客服工单不产生退款"):
        CustomerAfterSaleDetailResponse.model_validate(detail(**ticket))


def test_signal_sources_must_be_unique() -> None:
    signal = {
        "id": "s1",
        "kind": "RETURN_REQUESTS",
        "product_id": "p1",
        "product_name": "商品",
        "signal_date": "2026-09-21",
        "count": 2,
        "derived_from": [{"source_type": "AFTER_SALE", "source_id": "a1"}] * 2,
        "is_ignored": False,
        "ignore_reason": None,
    }
    with pytest.raises(ValidationError, match="来源记录不得重复"):
        CustomerSignal.model_validate(signal)


def test_reserved_stock_cannot_exceed_on_hand_and_available_is_derived() -> None:
    with pytest.raises(ValidationError, match="占用量不得超过在库量"):
        InventoryAlert.model_validate(alert(stock_reserved=11, stock_available=0))
    with pytest.raises(ValidationError, match="可售量必须等于在库量减占用量"):
        InventoryAlert.model_validate(alert(stock_available=5))


def test_fallback_source_entry_must_itself_be_marked_degraded() -> None:
    """来源条目层面的校验，不依赖整轮校验兜底。"""
    from app.schemas.v2.common import AnalysisSourceEntry

    with pytest.raises(ValidationError, match="规则兜底来源必须标记降级"):
        AnalysisSourceEntry(source="FALLBACK", degraded=False, degraded_reason=None)
    assert AnalysisSourceEntry(source="FALLBACK", degraded=True, degraded_reason="规则兜底")
