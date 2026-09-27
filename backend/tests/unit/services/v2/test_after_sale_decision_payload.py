"""售后决定草稿只能表达动作与回复，金额必须由应用时的订单快照计算。"""

import pytest
from pydantic import ValidationError

from app.services.v2.draft_handlers.after_sale_decision import DecisionPayload


def test_decision_payload_rejects_amount_and_requires_reason_for_rejection() -> None:
    with pytest.raises(ValidationError):
        DecisionPayload.model_validate({"decision": "REFUND", "amount": 99999})
    with pytest.raises(ValidationError):
        DecisionPayload.model_validate({"decision": "REJECT"})


def test_receipt_requires_explicit_sellable_choice() -> None:
    with pytest.raises(ValidationError):
        DecisionPayload.model_validate({"decision": "RECEIVE"})
    assert DecisionPayload.model_validate(
        {"decision": "RECEIVE", "sellable": False}
    ).sellable is False
