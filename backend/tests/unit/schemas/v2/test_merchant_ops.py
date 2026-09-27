"""商家经营只读面的传输边界，不访问数据库或模型。"""

import pytest
from pydantic import ValidationError

from app.schemas.v2 import merchant_ops, shop_session
from app.schemas.v2.merchant_ops import (
    BriefRegenerateRequest,
    CustomerSignal,
    DailyBriefResponse,
    InventoryAlert,
    InventoryAlertKind,
    SignalIgnoreRequest,
)

T0 = "2026-09-21T00:00:00Z"


def item(rank: int = 1, **changes: object) -> dict[str, object]:
    return {
        "rank": rank,
        "kind": "INVENTORY_ALERT",
        "title": "商品售罄",
        "evidence": "可售量为 0",
        "amount_cents": None,
        "next_action_prompt": "帮我起草补货草稿",
        **changes,
    }


def brief(**changes: object) -> dict[str, object]:
    return {
        "analysis_sources": [{"source": "DATABASE", "degraded": False, "degraded_reason": None}],
        "quality_status": "NOT_RUN",
        "quality_attempts": 0,
        "degraded": False,
        "degraded_reason": None,
        "brief_version": 1,
        "business_date": "2026-09-21",
        "business_timezone": "Asia/Shanghai",
        "data_as_of": T0,
        "generated_at": "2026-09-21T00:05:00Z",
        "trigger": "SCHEDULED",
        "items": [item()],
        "collapsed_count": 0,
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


def signal(**changes: object) -> dict[str, object]:
    return {
        "id": "s1",
        "kind": "RETURN_REQUESTS",
        "product_id": "p1",
        "product_name": "商品",
        "signal_date": "2026-09-21",
        "count": 3,
        "derived_from": [{"source_type": "AFTER_SALE", "source_id": "a1"}],
        "is_ignored": False,
        "ignore_reason": None,
        **changes,
    }


def test_brief_carries_version_and_business_date() -> None:
    fields = DailyBriefResponse.model_fields
    assert {"brief_version", "generated_at", "business_date", "data_as_of"} <= set(fields)
    assert DailyBriefResponse.model_validate(brief()).brief_version == 1


def test_brief_includes_degradation_fields() -> None:
    """R7：简报也必须披露降级。"""
    fields = DailyBriefResponse.model_fields
    assert {"analysis_sources", "degraded", "degraded_reason", "quality_status"} <= set(fields)
    with pytest.raises(ValidationError):
        DailyBriefResponse.model_validate(brief(degraded=True))
    fallback = [{"source": "FALLBACK", "degraded": False, "degraded_reason": None}]
    with pytest.raises(ValidationError):
        DailyBriefResponse.model_validate(brief(analysis_sources=fallback))


def test_brief_never_labels_rule_output_as_a_model_source() -> None:
    with pytest.raises(ValidationError):
        DailyBriefResponse.model_validate(
            brief(analysis_sources=[{"source": "LLM", "degraded": False, "degraded_reason": None}])
        )
    degraded = brief(
        analysis_sources=[{"source": "FALLBACK", "degraded": True, "degraded_reason": "规则生成"}],
        degraded=True,
        degraded_reason="规则生成",
        items=[],
    )
    assert DailyBriefResponse.model_validate(degraded).items == []


@pytest.mark.parametrize(
    "changes",
    [
        {"generated_at": "2026-09-20T23:59:59Z"},
        {"items": [item(2)]},
        {"items": [item(1), item(1)]},
        {"items": [item(i) for i in range(1, 8)]},
        {"brief_version": 0},
        {"collapsed_count": -1},
        {"trigger": "MANUAL"},
    ],
)
def test_brief_rejects_inconsistent_shapes(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DailyBriefResponse.model_validate(brief(**changes))


def test_regenerate_request_is_idempotent_and_body_is_minimal() -> None:
    assert BriefRegenerateRequest(client_request_id="r1")
    for payload in [{}, {"client_request_id": "r1", "force": True}]:
        with pytest.raises(ValidationError):
            BriefRegenerateRequest.model_validate(payload)


def test_signal_ignore_requires_reason() -> None:
    with pytest.raises(ValidationError):
        SignalIgnoreRequest.model_validate({"client_request_id": "r1"})
    for reason in ["", "   "]:
        with pytest.raises(ValidationError):
            SignalIgnoreRequest(client_request_id="r1", reason=reason)
    assert SignalIgnoreRequest(client_request_id="r1", reason=" 已处理 ").reason == "已处理"
    with pytest.raises(ValidationError):
        SignalIgnoreRequest.model_validate(
            {"client_request_id": "r1", "reason": "x", "buyer_key": "k"}
        )


def test_signal_declares_derived_source_and_no_buyer_identity() -> None:
    fields = set(CustomerSignal.model_fields)
    assert {"derived_from", "is_ignored"} <= fields
    assert not {"buyer_key", "buyer_alias", "merchant_id"} & fields
    assert CustomerSignal.model_validate(signal()).count == 3
    with pytest.raises(ValidationError):
        CustomerSignal.model_validate(signal(derived_from=[]))


@pytest.mark.parametrize(
    "changes",
    [
        {"is_ignored": True},
        {"ignore_reason": "原因"},
        {"product_name": None},
        {"count": 0},
        {
            "count": 1,
            "derived_from": [
                {"source_type": "AFTER_SALE", "source_id": "a1"},
                {"source_type": "AFTER_SALE", "source_id": "a2"},
            ],
        },
        {"derived_from": [{"source_type": "ORDER", "source_id": "o1"}]},
    ],
)
def test_signal_rejects_inconsistent_shapes(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CustomerSignal.model_validate(signal(**changes))


def test_ignored_signal_carries_reason() -> None:
    assert CustomerSignal.model_validate(signal(is_ignored=True, ignore_reason="已处理"))


def content_gap(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "CONTENT_GAP",
        "derived_from": [{"source_type": "PRODUCT", "source_id": "p1", "content_version": 2}],
    }
    return signal(**{**base, **changes})


def test_content_gap_signal_points_to_product_not_conversation() -> None:
    """PRD S2 / D11④：内容缺口信号只指向商品及其内容版本，不指向顾客对话。"""
    parsed = CustomerSignal.model_validate(content_gap())
    assert parsed.kind == "CONTENT_GAP"
    assert parsed.derived_from[0].content_version == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"product_id": None, "product_name": None},
        {"derived_from": [{"source_type": "PRODUCT", "source_id": "p2", "content_version": 2}]},
        {"derived_from": [{"source_type": "AFTER_SALE", "source_id": "a1"}]},
        {"derived_from": [{"source_type": "PRODUCT", "source_id": "p1"}]},
        {"derived_from": [{"source_type": "CONVERSATION", "source_id": "c1"}]},
    ],
)
def test_content_gap_rejects_foreign_sources(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CustomerSignal.model_validate(content_gap(**changes))


@pytest.mark.parametrize(
    "ref",
    [
        {"source_type": "PRODUCT", "source_id": "p1", "content_version": 1},
        {"source_type": "AFTER_SALE", "source_id": "a1", "content_version": 1},
    ],
)
def test_after_sale_signals_accept_only_after_sale_sources(ref: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CustomerSignal.model_validate(signal(derived_from=[ref]))


def test_inventory_alert_exposes_exact_triple_only_to_merchant() -> None:
    triple = {"stock_on_hand", "stock_reserved", "stock_available"}
    assert triple <= set(InventoryAlert.model_fields)
    for name in ("ProductSummary", "ProductDetailResponse"):
        assert not triple & set(getattr(shop_session, name).model_fields)
    assert not hasattr(merchant_ops, "StockBand")
    assert InventoryAlert.model_validate(alert()).stock_available == 4


def test_inventory_alert_kinds_are_closed() -> None:
    assert {k.value for k in InventoryAlertKind} == {"LOW_STOCK", "OUT_OF_STOCK", "SLOW_MOVING"}


@pytest.mark.parametrize(
    "changes",
    [
        {"stock_available": 5},
        {"stock_reserved": 11, "stock_available": -1},
        {"kind": "OUT_OF_STOCK"},
        {"kind": "LOW_STOCK", "low_stock_threshold": 3},
        {"kind": "LOW_STOCK", "stock_reserved": 10, "stock_available": 0},
        {"kind": "SLOW_MOVING", "stock_reserved": 10, "stock_available": 0},
        {"sold_last_30d": 0},
        {"sold_last_30d": 0, "days_of_supply": 4},
        {"days_of_supply": None},
        {"stock_on_hand": 10.5},
    ],
)
def test_inventory_alert_rejects_inconsistent_stock(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        InventoryAlert.model_validate(alert(**changes))


def test_zero_sales_has_unknown_days_of_supply() -> None:
    sold_out = alert(
        kind="OUT_OF_STOCK",
        stock_reserved=10,
        stock_available=0,
        sold_last_30d=0,
        days_of_supply=None,
    )
    assert InventoryAlert.model_validate(sold_out).days_of_supply is None
    slow = alert(kind="SLOW_MOVING", sold_last_30d=0, days_of_supply=None)
    assert InventoryAlert.model_validate(slow).kind == "SLOW_MOVING"
