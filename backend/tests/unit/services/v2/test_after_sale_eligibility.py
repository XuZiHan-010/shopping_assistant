"""售后资格仅由订单事实判定。"""

from datetime import UTC, datetime, timedelta

from app.schemas.v2.after_sales import AfterSaleType
from app.services.v2.after_sale_eligibility import OrderFacts, check_eligibility

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


def facts(**overrides: object) -> OrderFacts:
    values = {
        "lifecycle_origin": "V2",
        "payment_status": "PAID",
        "fulfillment_status": "DELIVERED",
        "delivered_at": NOW - timedelta(days=7),
        "already_in_progress": False,
        "already_refunded": False,
    }
    values.update(overrides)
    return OrderFacts(**values)


def test_seventh_day_allows_return_and_eighth_day_rejects_it() -> None:
    on_day_seven = check_eligibility(facts(), now=NOW)
    on_day_eight = check_eligibility(
        facts(delivered_at=NOW - timedelta(days=7, seconds=1)), now=NOW
    )
    assert on_day_seven.allowed_types == frozenset(AfterSaleType)
    assert AfterSaleType.RETURN_REFUND not in on_day_eight.allowed_types
    assert on_day_eight.reason_code == "WINDOW_EXPIRED"
    assert on_day_eight.rule_ref


def test_undelivered_order_only_allows_refund_or_ticket() -> None:
    result = check_eligibility(
        facts(fulfillment_status="IN_TRANSIT", delivered_at=None), now=NOW
    )
    assert result.allowed_types == frozenset(
        {AfterSaleType.REFUND_ONLY, AfterSaleType.TICKET}
    )
    assert result.reason_code == "ORDER_NOT_DELIVERED"
    assert result.rule_ref


def test_closed_and_legacy_orders_have_no_eligible_type() -> None:
    for order in (
        facts(payment_status="CLOSED"),
        facts(lifecycle_origin="LEGACY_V1"),
    ):
        result = check_eligibility(order, now=NOW)
        assert not result.allowed
        assert not result.allowed_types
        assert result.rule_ref


def test_in_progress_and_refunded_orders_are_rejected() -> None:
    for name, reason in (
        ("already_in_progress", "ALREADY_IN_PROGRESS"),
        ("already_refunded", "ALREADY_REFUNDED"),
    ):
        result = check_eligibility(facts(**{name: True}), now=NOW)
        assert not result.allowed
        assert result.reason_code == reason
        assert result.rule_ref
