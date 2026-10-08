"""售后 Agent 只能判定资格和准备界面预览。"""

import pytest
from pydantic import ValidationError

from app.tools.customer.after_sale import CheckAfterSaleArgs, PrepareAfterSaleArgs
from app.tools.types import WritePolicy


@pytest.mark.asyncio
async def test_english_eligibility_rejections_cover_each_policy_branch(monkeypatch) -> None:
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    import pytest

    from app.localization.locales import SupportedLocale
    from app.services.v2.after_sale_eligibility import OrderFacts
    from app.tools.customer import after_sale
    from app.tools.errors import GuardrailRejection
    from tests.unit.tools.tool_doubles import ctx_for, customer_session

    now = datetime.now(UTC)
    base = OrderFacts("V2", "PAID", "DELIVERED", now, False, False)
    branches = [
        (replace(base, payment_status="UNPAID"), "only paid orders"),
        (replace(base, already_refunded=True), "fully refunded"),
        (replace(base, already_in_progress=True), "multiple active"),
        (replace(base, fulfillment_status="NOT_SHIPPED"), "before delivery"),
        (replace(base, delivered_at=now - timedelta(days=8)), "seven days"),
        (base, "seven days"),
    ]
    ctx = replace(ctx_for(customer_session()), locale=SupportedLocale.EN_US)
    tools = {tool.name: tool for tool in after_sale.build_after_sale_tools(None)}
    for facts, expected in branches:
        async def fake_facts(*args, current=facts):
            return None, current

        monkeypatch.setattr(after_sale, "_facts", fake_facts)
        result = await tools["check_after_sale_eligibility"].executor(
            ctx, CheckAfterSaleArgs(order_id="test-order")
        )
        assert expected in result.payload["rule_ref"]
        if facts != base:
            with pytest.raises(GuardrailRejection) as rejected:
                await tools["prepare_after_sale"].executor(
                    ctx,
                    PrepareAfterSaleArgs(order_id="test-order", after_sale_type="RETURN_REFUND"),
                )
            assert expected in rejected.value.check.current_limit
            assert rejected.value.check.remediation == (
                "Explain which after-sales options the current policy allows."
            )


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
