"""售后 Agent 只能判定资格和准备界面预览。"""

from pydantic import ValidationError

from app.tools.customer.after_sale import CheckAfterSaleArgs, PrepareAfterSaleArgs
from app.tools.types import WritePolicy


def test_prepare_args_cannot_accept_amount_or_confirmation_token() -> None:
    base = {"order_id": "order-1", "after_sale_type": "TICKET", "reason": "坏了"}
    assert PrepareAfterSaleArgs.model_validate(base).reason == "坏了"
    for field in ("amount", "refund_amount_cents", "confirmation_token", "buyer_key"):
        try:
            PrepareAfterSaleArgs.model_validate({**base, field: "fake"})
        except ValidationError:
            pass
        else:
            raise AssertionError(f"不应接受模型提交 {field}")


def test_after_sale_tool_policies_are_read_and_confirmation_only() -> None:
    from app.tools.customer.after_sale import build_after_sale_tools

    specs = {spec.name: spec for spec in build_after_sale_tools(None)}  # type: ignore[arg-type]
    assert specs["check_after_sale_eligibility"].write_policy == WritePolicy.READ_ONLY
    assert specs["prepare_after_sale"].write_policy == WritePolicy.CUSTOMER_CONFIRMATION
    assert set(CheckAfterSaleArgs.model_fields) == {"order_id"}
