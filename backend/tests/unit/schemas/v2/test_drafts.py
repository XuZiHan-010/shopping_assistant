"""草稿审批与变更账本的传输边界，不访问数据库。"""

import pytest
from pydantic import ValidationError

from app.schemas.v2.common import MAX_MONEY_CENTS
from app.schemas.v2.drafts import (
    ChangeLedgerEntry,
    DraftApplyRequest,
    DraftApplyResponse,
    DraftDetailResponse,
    DraftDiffEntry,
    DraftKind,
    DraftState,
    DraftStateDetail,
    GuardrailCheckResult,
    VersionConflictDetail,
)

T0 = "2026-09-21T00:00:00Z"
T1 = "2026-09-28T00:00:00Z"


def entry(**changes: object) -> dict[str, object]:
    return {
        "entry_id": "en1",
        "target_type": "PRODUCT",
        "target_id": "p1",
        "field": "stock_on_hand",
        "unit": "COUNT",
        "before": 10,
        "after": 30,
        "is_preview": False,
        **changes,
    }


def summary(**changes: object) -> dict[str, object]:
    return {
        "id": "d1",
        "kind": "RESTOCK",
        "state": "STAGED",
        "title": "补货",
        "draft_version": 3,
        "target_version": 10,
        "created_at": T0,
        "updated_at": T0,
        "expires_at": T1,
        **changes,
    }


def detail(**changes: object) -> dict[str, object]:
    return {
        **summary(),
        "diff": {"entries": [entry()]},
        "guardrail_checks": [
            {"code": "MAX_DISCOUNT", "passed": True, "current_limit": None, "remediation": None}
        ],
        "guardrails_checked_at": T0,
        "approval_evidence": "ev.abc-123",
        "approval_evidence_expires_at": "2026-09-21T00:10:00Z",
        **changes,
    }


def ledger(**changes: object) -> dict[str, object]:
    return {
        "id": "l1",
        "draft_id": "d1",
        "kind": "RESTOCK",
        "drafted_by": {"actor_type": "AGENT", "label": "经营助手"},
        "approved_by": {"actor_type": "MERCHANT", "label": "Borough商家100"},
        "approved_at": T0,
        "applied_entry_ids": ["en1"],
        "guardrail_results": [],
        **changes,
    }


def test_draft_state_has_no_approved_value() -> None:
    """PRD §7.3 不变量 1：不存在可复用的『已批准』状态。"""
    assert {s.value for s in DraftState} == {"STAGED", "APPLIED", "DISCARDED", "EXPIRED"}
    with pytest.raises(ValidationError):
        DraftStateDetail.model_validate({"state": "APPROVED"})


def test_draft_kind_is_closed() -> None:
    assert {k.value for k in DraftKind} == {
        "RESTOCK",
        "CONTENT_CHANGE",
        "PRICE_CHANGE",
        "COUPON",
        "AFTER_SALE_DECISION",
    }


def test_apply_requires_both_versions() -> None:
    complete = {
        "client_request_id": "r1",
        "draft_version": 3,
        "target_version": 7,
        "approval_evidence": "e1",
    }
    assert DraftApplyRequest.model_validate(complete).accepted_entry_ids is None
    for missing in ("draft_version", "target_version", "client_request_id"):
        with pytest.raises(ValidationError):
            DraftApplyRequest.model_validate({k: v for k, v in complete.items() if k != missing})


def test_apply_requires_approval_evidence() -> None:
    with pytest.raises(ValidationError):
        DraftApplyRequest.model_validate(
            {"client_request_id": "r1", "draft_version": 3, "target_version": 7}
        )
    with pytest.raises(ValidationError):
        DraftApplyRequest.model_validate(
            {
                "client_request_id": "r1",
                "draft_version": 3,
                "target_version": 7,
                "approval_evidence": "bad evidence!",
            }
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"draft_version": 0},
        {"target_version": -1},
        {"draft_version": 1.5},
        {"draft_version": True},
        {"accepted_entry_ids": []},
        {"accepted_entry_ids": ["a", "a"]},
        {"state": "APPROVED"},
        {"merchant_id": "m1"},
    ],
)
def test_apply_rejects_malformed_input(changes: dict[str, object]) -> None:
    base = {
        "client_request_id": "r1",
        "draft_version": 3,
        "target_version": 7,
        "approval_evidence": "e1",
    }
    with pytest.raises(ValidationError):
        DraftApplyRequest.model_validate({**base, **changes})


def test_draft_detail_issues_version_bound_approval_evidence() -> None:
    fields = DraftDetailResponse.model_fields
    assert {"approval_evidence", "approval_evidence_expires_at", "draft_version"} <= set(fields)
    assert DraftDetailResponse.model_validate(detail()).approval_evidence == "ev.abc-123"


def test_evidence_only_exists_on_staged_drafts() -> None:
    with pytest.raises(ValidationError):
        DraftDetailResponse.model_validate(detail(state="APPLIED"))
    with pytest.raises(ValidationError):
        DraftDetailResponse.model_validate(detail(approval_evidence=None))
    with pytest.raises(ValidationError):
        DraftDetailResponse.model_validate(detail(approval_evidence_expires_at=None))
    finished = detail(state="DISCARDED", approval_evidence=None, approval_evidence_expires_at=None)
    assert DraftDetailResponse.model_validate(finished).approval_evidence is None


def test_summary_time_ordering() -> None:
    for changes in [{"updated_at": "2026-09-20T00:00:00Z"}, {"expires_at": T0}]:
        with pytest.raises(ValidationError):
            DraftDetailResponse.model_validate(detail(**changes))


def test_batch_id_defaults_to_none() -> None:
    """未提供 batch_id 的既有草稿（单份补货/调价/券）仍能正常解析（N3 阶段 C 新增字段）。"""

    from app.schemas.v2.drafts import DraftSummary

    parsed = DraftSummary.model_validate(summary())
    assert parsed.batch_id is None


def test_batch_id_allowed_only_for_content_change() -> None:
    """只有 CONTENT_CHANGE（商品内容批量起草）可以有非空 batch_id；其余种类必须是 null。"""

    from app.schemas.v2.drafts import DraftSummary

    allowed = DraftSummary.model_validate(summary(kind="CONTENT_CHANGE", batch_id="batch-1"))
    assert allowed.batch_id == "batch-1"

    with pytest.raises(ValidationError):
        DraftSummary.model_validate(summary(kind="RESTOCK", batch_id="batch-1"))
    with pytest.raises(ValidationError):
        DraftSummary.model_validate(summary(kind="PRICE_CHANGE", batch_id="batch-1"))
    with pytest.raises(ValidationError):
        DraftSummary.model_validate(summary(kind="COUPON", batch_id="batch-1"))


@pytest.mark.parametrize(
    "changes",
    [
        {"unit": "COUNT", "before": -1},
        {"unit": "CENTS", "after": MAX_MONEY_CENTS + 1},
        {"unit": "CENTS", "after": 1.5},
        {"unit": "COUNT", "after": True},
        {"unit": "TEXT", "after": 1},
        {"unit": "BOOL", "after": 1},
        {"unit": "TEXT", "before": None, "after": "x" * 2001},
        {"target_type": "ORDER"},
    ],
)
def test_diff_values_must_match_unit(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DraftDiffEntry.model_validate(entry(**changes))


def test_diff_values_accept_matching_units() -> None:
    for unit, before, after in [
        ("TEXT", "旧", "新"),
        ("CENTS", 100, MAX_MONEY_CENTS),
        ("BPS", 9000, 8000),
        ("BOOL", False, True),
        ("COUNT", None, 5),
    ]:
        assert DraftDiffEntry.model_validate(entry(unit=unit, before=before, after=after))


def test_after_sale_amounts_are_preview_only() -> None:
    money = entry(target_type="AFTER_SALE", field="refund", unit="CENTS", after=900)
    kind = {"kind": "AFTER_SALE_DECISION"}
    with pytest.raises(ValidationError):
        DraftDetailResponse.model_validate(detail(**kind, diff={"entries": [money]}))
    preview = {**money, "is_preview": True}
    assert DraftDetailResponse.model_validate(detail(**kind, diff={"entries": [preview]}))
    with pytest.raises(ValidationError):
        DraftDetailResponse.model_validate(
            detail(diff={"entries": [{**entry(), "is_preview": True}]})
        )


def test_diff_entries_are_unique_and_non_empty() -> None:
    with pytest.raises(ValidationError):
        DraftDetailResponse.model_validate(detail(diff={"entries": []}))
    with pytest.raises(ValidationError):
        DraftDetailResponse.model_validate(detail(diff={"entries": [entry(), entry()]}))


def test_failed_guardrail_explains_limit_and_remedy() -> None:
    assert GuardrailCheckResult(
        code="MAX_DISCOUNT", passed=False, current_limit="不超过 20%", remediation="降低优惠幅度"
    )
    for payload in [
        {"code": "MAX_DISCOUNT", "passed": False, "current_limit": None, "remediation": None},
        {"code": "max_discount", "passed": True, "current_limit": None, "remediation": None},
    ]:
        with pytest.raises(ValidationError):
            GuardrailCheckResult.model_validate(payload)


def test_ledger_entry_records_both_actors() -> None:
    fields = ChangeLedgerEntry.model_fields
    assert {"drafted_by", "approved_by", "approved_at", "guardrail_results"} <= set(fields)
    assert ChangeLedgerEntry.model_validate(ledger())
    bad_approver = {"actor_type": "AGENT", "label": "经营助手"}
    failed = {"code": "X", "passed": False, "current_limit": "a", "remediation": "b"}
    for changes in [
        {"approved_by": bad_approver},
        {"applied_entry_ids": []},
        {"applied_entry_ids": ["a", "a"]},
        {"guardrail_results": [failed]},
        {"session_id": "s"},
    ]:
        with pytest.raises(ValidationError):
            ChangeLedgerEntry.model_validate(ledger(**changes))


def test_apply_response_links_applied_draft_and_ledger() -> None:
    applied = summary(state="APPLIED")
    assert DraftApplyResponse.model_validate({"draft": applied, "ledger_entry": ledger()})
    for draft, entry_changes in [
        (summary(state="STAGED"), {}),
        (applied, {"draft_id": "other"}),
        (applied, {"kind": "COUPON"}),
    ]:
        with pytest.raises(ValidationError):
            DraftApplyResponse.model_validate(
                {"draft": draft, "ledger_entry": ledger(**entry_changes)}
            )


def test_error_detail_shapes_leak_nothing_else() -> None:
    assert set(VersionConflictDetail.model_fields) == {"scope"}
    assert set(DraftStateDetail.model_fields) == {"state"}
    with pytest.raises(ValidationError):
        VersionConflictDetail.model_validate({"scope": "TARGET", "current_version": 9})
