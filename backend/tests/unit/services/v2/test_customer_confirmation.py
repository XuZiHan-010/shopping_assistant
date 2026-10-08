"""顾客售后令牌绑定整个请求、会话与店铺，且与审批用途隔离。"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.core.errors import ConfirmationRequiredError
from app.services.v2.approval_evidence import (
    ApprovalEvidenceService,
    CustomerConfirmationBinding,
)

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)
BINDING = CustomerConfirmationBinding(
    session_record_id="session-1",
    merchant_id="merchant-1",
    buyer_digest="buyer-digest-1",
    order_id="order-1",
    after_sale_type="RETURN_REFUND",
    request_digest="request-digest-1",
)


def test_customer_confirmation_cannot_be_rebound_or_used_for_draft() -> None:
    service = ApprovalEvidenceService(secret="test-secret", purpose="customer-confirmation:v1")
    token = service.issue(BINDING, now=NOW).token
    assert service.verify(token, BINDING, now=NOW)
    for field, value in (
        ("session_record_id", "session-2"),
        ("merchant_id", "merchant-2"),
        ("buyer_digest", "buyer-digest-2"),
        ("order_id", "order-2"),
        ("after_sale_type", "TICKET"),
        ("request_digest", "request-digest-2"),
    ):
        with pytest.raises(ConfirmationRequiredError):
            service.verify(token, replace(BINDING, **{field: value}), now=NOW)
    with pytest.raises(ConfirmationRequiredError):
        ApprovalEvidenceService(secret="test-secret").verify(token, BINDING, now=NOW)
