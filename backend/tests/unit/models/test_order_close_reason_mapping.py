"""关闭原因的存储兼容值与冻结 API 枚举必须完整、可逆地转换。"""

import pytest

from app.domain.order_status_mapping import (
    close_reason_from_api,
    close_reason_to_api,
    from_legacy_status,
    to_legacy_status,
)
from app.schemas.v2.trade import CloseReason


@pytest.mark.parametrize(
    ("legacy", "stored", "public"),
    [
        ("CANCELLED", "CUSTOMER_CANCEL", CloseReason.USER_CANCELLED),
        ("CLOSED", "TIMEOUT", CloseReason.PAYMENT_TIMEOUT),
    ],
)
def test_closed_order_roundtrips_through_public_contract(legacy, stored, public):
    payment, fulfillment, reason = from_legacy_status(legacy)
    assert reason == stored
    assert CloseReason(close_reason_to_api(reason)) is public
    assert close_reason_from_api(public) == stored
    assert to_legacy_status(payment, fulfillment, close_reason_from_api(public)) == legacy


def test_every_public_close_reason_has_a_storage_mapping():
    assert {close_reason_to_api(close_reason_from_api(reason)) for reason in CloseReason} == {
        reason.value for reason in CloseReason
    }


def test_open_order_preserves_null_close_reason():
    assert close_reason_to_api(None) is None
    assert close_reason_from_api(None) is None


@pytest.mark.parametrize("reason", ["", "UNKNOWN", "USER_CANCELLED", "PAYMENT_TIMEOUT"])
def test_storage_mapper_rejects_unknown_or_wrong_boundary_values(reason):
    with pytest.raises(ValueError):
        close_reason_to_api(reason)


@pytest.mark.parametrize("reason", ["", "UNKNOWN", "CUSTOMER_CANCEL", "TIMEOUT"])
def test_api_mapper_rejects_unknown_or_wrong_boundary_values(reason):
    with pytest.raises(ValueError):
        close_reason_from_api(reason)
