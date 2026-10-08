"""审批证据的签名与绑定语义（契约 §8.7.9、§8.13.2 不变量 6）。

这些用例只管令牌本身：签名、绑定、有效期。nonce 的一次性消费必须在真实数据库上验证，
在 `tests/integration/v2/test_approval_evidence_db.py`。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter

from app.core.errors import ConfirmationRequiredError
from app.schemas.v2.drafts import ApprovalEvidence as EvidenceField
from app.services.v2.approval_evidence import (
    EVIDENCE_PURPOSE,
    ApprovalBinding,
    ApprovalEvidenceService,
    EvidenceRejection,
)

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
SECRET = "unit-test-signing-secret"

BINDING = ApprovalBinding(
    session_record_id="11111111-1111-1111-1111-111111111111",
    merchant_id="22222222-2222-2222-2222-222222222222",
    draft_id="33333333-3333-3333-3333-333333333333",
    draft_version=1,
    target_version=12,
)


@pytest.fixture
def service() -> ApprovalEvidenceService:
    return ApprovalEvidenceService(secret=SECRET)


def test_issued_token_verifies_against_the_same_binding(service: ApprovalEvidenceService) -> None:
    issued = service.issue(BINDING, now=NOW)

    verified = service.verify(issued.token, BINDING, now=NOW)

    assert verified.nonce == issued.nonce
    assert issued.expires_at == NOW + timedelta(minutes=10)


def test_token_matches_the_contract_charset(service: ApprovalEvidenceService) -> None:
    """§8.13.1：`approval_evidence` 只允许 `A-Za-z0-9._~-`。"""

    issued = service.issue(BINDING, now=NOW)

    assert TypeAdapter(EvidenceField).validate_python(issued.token) == issued.token


def test_each_issue_uses_a_fresh_nonce(service: ApprovalEvidenceService) -> None:
    """重复读取详情可以签发多个 nonce，但每个只能消费一次。"""

    first = service.issue(BINDING, now=NOW)
    second = service.issue(BINDING, now=NOW)

    assert first.nonce != second.nonce
    assert first.token != second.token


def test_token_does_not_leak_the_secret_or_identifiers(service: ApprovalEvidenceService) -> None:
    issued = service.issue(BINDING, now=NOW)

    assert SECRET not in issued.token
    assert BINDING.merchant_id not in issued.token
    assert BINDING.session_record_id not in issued.token


def test_tampered_token_is_rejected(service: ApprovalEvidenceService) -> None:
    issued = service.issue(BINDING, now=NOW)
    payload, _, signature = issued.token.partition(".")

    with pytest.raises(ConfirmationRequiredError):
        service.verify(f"{payload}A.{signature}", BINDING, now=NOW)


def test_token_signed_with_another_secret_is_rejected() -> None:
    forged = ApprovalEvidenceService(secret="another-secret").issue(BINDING, now=NOW)

    with pytest.raises(ConfirmationRequiredError):
        ApprovalEvidenceService(secret=SECRET).verify(forged.token, BINDING, now=NOW)


def test_subkey_is_purpose_scoped(service: ApprovalEvidenceService) -> None:
    """用途不同的子密钥互不通用：售后确认的证据不能用来批准草稿。"""

    other_purpose = ApprovalEvidenceService(secret=SECRET, purpose="customer-confirmation:v1")
    forged = other_purpose.issue(BINDING, now=NOW)

    with pytest.raises(ConfirmationRequiredError):
        service.verify(forged.token, BINDING, now=NOW)


def test_token_expires_after_ten_minutes(service: ApprovalEvidenceService) -> None:
    issued = service.issue(BINDING, now=NOW)

    service.verify(issued.token, BINDING, now=NOW + timedelta(minutes=9, seconds=59))
    with pytest.raises(ConfirmationRequiredError):
        service.verify(issued.token, BINDING, now=NOW + timedelta(minutes=10, seconds=1))


@pytest.mark.parametrize(
    "change",
    [
        {"session_record_id": "99999999-9999-9999-9999-999999999999"},
        {"merchant_id": "99999999-9999-9999-9999-999999999999"},
        {"draft_id": "99999999-9999-9999-9999-999999999999"},
        {"draft_version": 2},
        {"target_version": 13},
    ],
)
def test_binding_mismatch_is_rejected(
    service: ApprovalEvidenceService, change: dict[str, object]
) -> None:
    """主体、资源、版本任一不符都不接受（§8.7.9）。"""

    issued = service.issue(BINDING, now=NOW)

    with pytest.raises(ConfirmationRequiredError):
        service.verify(issued.token, replace(BINDING, **change), now=NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize("garbage", ["", ".", "abc", "abc.def", "!!!.???", "a" * 3000])
def test_garbage_tokens_are_rejected(service: ApprovalEvidenceService, garbage: str) -> None:
    with pytest.raises(ConfirmationRequiredError):
        service.verify(garbage, BINDING, now=NOW)


def test_rejection_reason_stays_internal(service: ApprovalEvidenceService) -> None:
    """内部审计可以记原因枚举，对外只有同一个中性错误——且永远不含令牌原值。"""

    issued = service.issue(BINDING, now=NOW)

    with pytest.raises(ConfirmationRequiredError) as exc:
        service.verify(issued.token, replace(BINDING, draft_version=2), now=NOW)

    assert exc.value.details == []
    assert issued.token not in str(exc.value)
    assert set(EvidenceRejection) >= {EvidenceRejection.BINDING_MISMATCH}


def test_purpose_is_the_contract_value(service: ApprovalEvidenceService) -> None:
    assert EVIDENCE_PURPOSE == "draft-approval:v1"
    assert service.purpose == EVIDENCE_PURPOSE
