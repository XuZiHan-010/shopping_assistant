"""售后决定工具面只允许起草，参数不含金额与审批凭证。"""

from app.tools.merchant.after_sale import DraftAfterSaleDecisionArgs


def test_decision_tool_does_not_accept_amount_or_approval() -> None:
    fields = DraftAfterSaleDecisionArgs.model_json_schema()["properties"]
    assert not any("amount" in name or "approval" in name for name in fields)
