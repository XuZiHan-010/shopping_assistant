"""售后列表工具的状态筛选参数。

2026-10-07 真实复测：模型传了 `state="PENDING"`，真实取值是 `PENDING_MERCHANT`。
参数当时是自由字符串，工具返回 0 条而不是报错，模型据此告诉商家「没有待处理的售后」。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.tools.merchant.after_sale import ListAfterSalesArgs


def test_unknown_state_is_rejected_instead_of_silently_matching_nothing() -> None:
    with pytest.raises(ValidationError):
        ListAfterSalesArgs(state="PENDING")


def test_real_states_and_no_filter_are_accepted() -> None:
    assert ListAfterSalesArgs(state="PENDING_MERCHANT").state == "PENDING_MERCHANT"
    assert ListAfterSalesArgs().state is None


def test_schema_shown_to_the_model_lists_the_valid_states() -> None:
    schema = json.dumps(ListAfterSalesArgs.model_json_schema())

    for state in ("PENDING_MERCHANT", "AWAITING_CUSTOMER_INFO", "REFUNDED", "CLOSED"):
        assert state in schema
