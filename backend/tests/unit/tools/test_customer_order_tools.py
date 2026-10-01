"""WS 顾客订单只读工具的模型可见参数与权限。"""

import pytest
from pydantic import ValidationError

from app.tools.customer.orders import GetMyOrderArgs, build_order_tools
from app.tools.types import ToolRole, WritePolicy


def test_args_accept_only_order_id() -> None:
    assert GetMyOrderArgs.model_validate({"order_id": "o-1"}).order_id == "o-1"
    for field in ("buyer_key", "merchant_id", "include_all"):
        with pytest.raises(ValidationError):
            GetMyOrderArgs.model_validate({"order_id": "o-1", field: "x"})


def test_tool_is_customer_read_only() -> None:
    (spec,) = build_order_tools(None)  # type: ignore[arg-type]
    assert spec.name == "get_my_order"
    assert spec.roles == frozenset({ToolRole.CUSTOMER})
    assert spec.write_policy == WritePolicy.READ_ONLY
    assert spec.parallelizable is True
