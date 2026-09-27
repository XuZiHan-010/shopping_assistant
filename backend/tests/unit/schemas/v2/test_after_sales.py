"""售后契约的传输边界与状态机，不访问数据库。"""

import pytest
from pydantic import ValidationError

from app.schemas.v2.after_sales import (
    ALLOWED_TRANSITIONS,
    AfterSaleConfirmationChallenge,
    AfterSaleCreateRequest,
    AfterSaleIneligibleDetail,
    AfterSaleState,
    AfterSaleSummary,
    AfterSaleSupplementRequest,
    AfterSaleType,
    ConversationSnapshot,
    CustomerAfterSaleDetailResponse,
    MerchantAfterSaleDetailResponse,
    MerchantAfterSaleSummary,
    is_allowed_transition,
)

T0 = "2026-09-21T00:00:00Z"
T1 = "2026-09-21T01:00:00Z"
S = AfterSaleState
K = AfterSaleType


def snapshot(**changes: object) -> dict[str, object]:
    return {
        "order_item_id": "oi1",
        "product_id": "p1",
        "name": "商品",
        "quantity": 2,
        "unit_price_cents": 500,
        "discount_cents": 100,
        "line_total_cents": 900,
        **changes,
    }


def events(*states: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    previous: str | None = None
    for index, state in enumerate(states):
        result.append(
            {
                "id": f"e{index}",
                "from_state": previous,
                "to_state": state,
                "actor": "CUSTOMER" if previous is None else "MERCHANT",
                "occurred_at": T0,
            }
        )
        previous = state
    return result


def detail(**changes: object) -> dict[str, object]:
    return {
        "id": "a1",
        "order_id": "o1",
        "after_sale_type": "REFUND_ONLY",
        "state": "APPROVED",
        "refund_amount_cents": 900,
        "created_at": T0,
        "updated_at": T1,
        "reason": "质量问题",
        "lines": [{"snapshot": snapshot(), "refund_cents": 900}],
        "events": events("PENDING_MERCHANT", "APPROVED"),
        "supplements": [],
        "replies": [],
        **changes,
    }


def merchant_detail(**changes: object) -> dict[str, object]:
    return {
        **detail(),
        "buyer_alias": "顾客-7F3A",
        "first_response_due_at": T1,
        "ticket_id": "t1",
        "conversation_summary": {"status": "NOT_SHARED", "text": None, "unavailable_reason": None},
        **changes,
    }


def test_after_sale_create_rejects_client_supplied_amount() -> None:
    """退款金额由后端按价格快照算，客户端不得提交。"""
    with pytest.raises(ValidationError, match="refund_amount_cents"):
        AfterSaleCreateRequest.model_validate(
            {
                "client_request_id": "r1",
                "order_id": "o1",
                "after_sale_type": "REFUND_ONLY",
                "confirmation_token": "t1",
                "refund_amount_cents": 99999,
            }
        )


def test_supplement_request_rejects_empty_note_and_client_decisions() -> None:
    assert AfterSaleSupplementRequest.model_validate(
        {"client_request_id": "s1", "note": " 补充说明 "}
    ).note == "补充说明"
    for payload in (
        {"note": ""},
        {"note": "x" * 1001},
        {"note": "补充", "amount": 100},
        {"note": "补充", "state": "APPROVED"},
    ):
        with pytest.raises(ValidationError):
            AfterSaleSupplementRequest.model_validate({"client_request_id": "s1", **payload})


def test_detail_requires_ordered_supplements() -> None:
    one = {"id": "s1", "note": "说明一", "submitted_at": T0}
    two = {"id": "s2", "note": "说明二", "submitted_at": T1}
    base = {**detail(supplements=[one, two]), "conversation_summary_shared": True}
    assert len(CustomerAfterSaleDetailResponse.model_validate(base).supplements) == 2
    for bad in ([], [two, one], [{**one, "note": ""}], [{**one, "amount": 100}]):
        payload = (
            {**base, "supplements": bad}
            if bad
            else {key: value for key, value in base.items() if key != "supplements"}
        )
        with pytest.raises(ValidationError):
            CustomerAfterSaleDetailResponse.model_validate(payload)


@pytest.mark.parametrize(
    "field", ["eligible", "state", "buyer_key", "merchant_id", "refund_cents", "amount"]
)
def test_after_sale_create_rejects_backend_decided_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        AfterSaleCreateRequest.model_validate(
            {
                "client_request_id": "r1",
                "order_id": "o1",
                "after_sale_type": "REFUND_ONLY",
                field: 1,
            }
        )


def test_after_sale_create_can_enter_confirmation_challenge_phase() -> None:
    request = AfterSaleCreateRequest(
        client_request_id="r1", order_id="o1", after_sale_type=AfterSaleType.REFUND_ONLY
    )
    assert request.confirmation_token is None
    assert request.order_item_ids == []
    assert request.include_conversation_summary is False


def test_after_sale_create_validates_lines_reason_and_token() -> None:
    base = {"client_request_id": "r1", "order_id": "o1", "after_sale_type": "RETURN_REFUND"}
    with pytest.raises(ValidationError):
        AfterSaleCreateRequest.model_validate({**base, "order_item_ids": ["a", "a"]})
    with pytest.raises(ValidationError):
        AfterSaleCreateRequest.model_validate({**base, "confirmation_token": "bad token!"})
    with pytest.raises(ValidationError):
        AfterSaleCreateRequest.model_validate({**base, "after_sale_type": "TICKET"})
    ticket = AfterSaleCreateRequest.model_validate(
        {**base, "after_sale_type": "TICKET", "reason": " 商品有问题 "}
    )
    assert ticket.reason == "商品有问题"
    with pytest.raises(ValidationError):
        AfterSaleCreateRequest.model_validate({**base, "client_request_id": ""})


def test_confirmation_challenge_is_distinct_from_created_after_sale() -> None:
    assert {"confirmation_token", "expires_at", "summary"} <= set(
        AfterSaleConfirmationChallenge.model_fields
    )
    assert "confirmation_token" not in AfterSaleSummary.model_fields
    challenge = {
        "confirmation_token": "abc.def-ghi",
        "expires_at": T1,
        "summary": {
            "order_id": "o1",
            "after_sale_type": "REFUND_ONLY",
            "lines": [
                {"order_item_id": "oi1", "name": "商品", "quantity": 2, "line_total_cents": 900}
            ],
            "estimated_refund_cents": 900,
            "reason": "",
            "conversation_summary_status": "NOT_SHARED",
            "conversation_summary": None,
        },
    }
    assert AfterSaleConfirmationChallenge.model_validate(challenge)
    bad = {**challenge, "summary": {**challenge["summary"], "estimated_refund_cents": None}}  # type: ignore[dict-item]
    with pytest.raises(ValidationError):
        AfterSaleConfirmationChallenge.model_validate(bad)


def test_ineligible_detail_names_a_rule() -> None:
    assert AfterSaleIneligibleDetail(reason="WINDOW_EXPIRED", rule_reference="平台售后规则 3.2")
    with pytest.raises(ValidationError):
        AfterSaleIneligibleDetail.model_validate({"reason": "WINDOW_EXPIRED", "rule_reference": ""})
    with pytest.raises(ValidationError):
        AfterSaleIneligibleDetail.model_validate({"reason": "OTHER", "rule_reference": "x"})


def test_merchant_detail_uses_alias_never_buyer_key() -> None:
    fields = MerchantAfterSaleDetailResponse.model_fields
    assert "buyer_alias" in fields
    assert not {"buyer_key", "viewed_audit_id", "audit_id", "merchant_id"} & set(fields)
    assert "buyer_key" not in MerchantAfterSaleSummary.model_fields
    assert MerchantAfterSaleDetailResponse.model_validate(merchant_detail()).ticket_id == "t1"
    with pytest.raises(ValidationError):
        MerchantAfterSaleDetailResponse.model_validate({**merchant_detail(), "buyer_key": "k"})


def test_customer_detail_has_no_alias_or_audit_fields() -> None:
    fields = CustomerAfterSaleDetailResponse.model_fields
    assert not {"buyer_alias", "viewed_audit_id", "audit_id", "ticket_id"} & set(fields)
    assert CustomerAfterSaleDetailResponse.model_validate(
        {**detail(), "conversation_summary_shared": False}
    )


def test_conversation_snapshot_pairs_status_with_content() -> None:
    assert ConversationSnapshot(status="AVAILABLE", text="摘要", unavailable_reason=None)
    assert ConversationSnapshot(status="UNAVAILABLE", text=None, unavailable_reason="生成失败")
    for status, text, reason in [
        ("AVAILABLE", None, None),
        ("NOT_SHARED", "泄露", None),
        ("UNAVAILABLE", None, None),
        ("AVAILABLE", "摘要", "多余"),
    ]:
        with pytest.raises(ValidationError):
            ConversationSnapshot.model_validate(
                {"status": status, "text": text, "unavailable_reason": reason}
            )


def test_refund_never_exceeds_line_snapshot_and_sums_to_total() -> None:
    over = {"snapshot": snapshot(), "refund_cents": 901}
    with pytest.raises(ValidationError):
        CustomerAfterSaleDetailResponse.model_validate(
            {**detail(refund_amount_cents=901, lines=[over]), "conversation_summary_shared": False}
        )
    with pytest.raises(ValidationError):
        CustomerAfterSaleDetailResponse.model_validate(
            {**detail(refund_amount_cents=100), "conversation_summary_shared": False}
        )


def test_detail_rejects_broken_event_chains() -> None:
    def build(**changes: object) -> dict[str, object]:
        return {**detail(**changes), "conversation_summary_shared": False}

    assert CustomerAfterSaleDetailResponse.model_validate(build())
    for changes in [
        {"state": "PENDING_MERCHANT"},
        {"events": events("APPROVED")},
        {"events": events("PENDING_MERCHANT", "REFUNDED"), "state": "REFUNDED"},
        {
            "events": events("PENDING_MERCHANT", "APPROVED", "AWAITING_RETURN"),
            "state": "AWAITING_RETURN",
        },
    ]:
        with pytest.raises(ValidationError):
            CustomerAfterSaleDetailResponse.model_validate(build(**changes))


def test_detail_rejects_out_of_order_events() -> None:
    history = events("PENDING_MERCHANT", "APPROVED")
    history[0]["occurred_at"] = T1
    history[1]["occurred_at"] = T0
    with pytest.raises(ValidationError, match="事件必须按时间与标识升序排列"):
        CustomerAfterSaleDetailResponse.model_validate(
            {**detail(events=history), "conversation_summary_shared": False}
        )


def test_detail_rejects_descending_ids_when_event_times_match() -> None:
    history = events("PENDING_MERCHANT", "APPROVED")
    history[0]["id"] = "e2"
    history[1]["id"] = "e1"
    with pytest.raises(ValidationError, match="事件必须按时间与标识升序排列"):
        CustomerAfterSaleDetailResponse.model_validate(
            {**detail(events=history), "conversation_summary_shared": False}
        )


def test_information_round_limit_reserves_room_to_close_longest_case() -> None:
    history = events("PENDING_MERCHANT")
    for _ in range(47):
        history.extend(events("AWAITING_CUSTOMER_INFO", "PENDING_MERCHANT"))
    for index, event in enumerate(history):
        event["id"] = f"e{index:03d}"
        if index:
            event["from_state"] = history[index - 1]["to_state"]
        event["actor"] = "MERCHANT" if event["to_state"] == "AWAITING_CUSTOMER_INFO" else "CUSTOMER"
    closure = ["APPROVED", "AWAITING_RETURN", "RECEIVED", "REFUNDED", "CLOSED"]
    for state in closure:
        index = len(history)
        history.append(
            {
                "id": f"e{index:03d}",
                "from_state": history[-1]["to_state"],
                "to_state": state,
                "actor": "MERCHANT",
                "occurred_at": T0,
            }
        )
    assert len(history) == 100
    payload = detail(after_sale_type="RETURN_REFUND", state="CLOSED", events=history)
    assert CustomerAfterSaleDetailResponse.model_validate(
        {**payload, "conversation_summary_shared": False}
    )

    over_limit = history[:95]
    over_limit.append(
        {
            "id": "e095",
            "from_state": "PENDING_MERCHANT",
            "to_state": "AWAITING_CUSTOMER_INFO",
            "actor": "MERCHANT",
            "occurred_at": T0,
        }
    )
    with pytest.raises(ValidationError, match="补充信息次数已达上限"):
        CustomerAfterSaleDetailResponse.model_validate(
            {
                **detail(
                    after_sale_type="RETURN_REFUND",
                    state="AWAITING_CUSTOMER_INFO",
                    events=over_limit,
                ),
                "conversation_summary_shared": False,
            }
        )


def test_information_request_transition_requires_current_round_count() -> None:
    with pytest.raises(ValueError, match="补充信息次数"):
        is_allowed_transition(K.RETURN_REFUND, S.PENDING_MERCHANT, S.AWAITING_CUSTOMER_INFO)
    assert is_allowed_transition(
        K.RETURN_REFUND,
        S.PENDING_MERCHANT,
        S.AWAITING_CUSTOMER_INFO,
        prior_information_requests=46,
    )
    assert not is_allowed_transition(
        K.RETURN_REFUND,
        S.PENDING_MERCHANT,
        S.AWAITING_CUSTOMER_INFO,
        prior_information_requests=47,
    )


def test_ticket_has_no_refund_and_may_close_after_approval() -> None:
    ticket = detail(
        after_sale_type="TICKET",
        refund_amount_cents=None,
        lines=[],
        state="CLOSED",
        events=events("PENDING_MERCHANT", "APPROVED", "CLOSED"),
    )
    assert CustomerAfterSaleDetailResponse.model_validate(
        {**ticket, "conversation_summary_shared": False}
    )
    with pytest.raises(ValidationError):
        CustomerAfterSaleDetailResponse.model_validate(
            {**ticket, "refund_amount_cents": 0, "conversation_summary_shared": False}
        )


def test_transition_table_matches_prd_chains_exactly() -> None:
    """PRD §7.2 四条链逐跳可走，且表内没有多余跳转。"""
    chains = {
        K.RETURN_REFUND: [
            (S.PENDING_MERCHANT, S.APPROVED),
            (S.APPROVED, S.AWAITING_RETURN),
            (S.AWAITING_RETURN, S.RECEIVED),
            (S.RECEIVED, S.REFUNDED),
            (S.REFUNDED, S.CLOSED),
        ],
        K.REFUND_ONLY: [
            (S.PENDING_MERCHANT, S.APPROVED),
            (S.APPROVED, S.REFUNDED),
            (S.REFUNDED, S.CLOSED),
        ],
        K.TICKET: [
            (S.PENDING_MERCHANT, S.APPROVED),
            (S.APPROVED, S.CLOSED),
        ],
    }
    for kind, hops in chains.items():
        for source, target in hops:
            assert is_allowed_transition(kind, source, target)
    for kind in K:
        assert is_allowed_transition(kind, S.PENDING_MERCHANT, S.REJECTED)
        assert is_allowed_transition(kind, S.REJECTED, S.CLOSED)
        assert is_allowed_transition(
            kind, S.PENDING_MERCHANT, S.AWAITING_CUSTOMER_INFO, prior_information_requests=0
        )
        assert is_allowed_transition(kind, S.AWAITING_CUSTOMER_INFO, S.PENDING_MERCHANT)
        assert is_allowed_transition(kind, None, S.PENDING_MERCHANT)

    prd_edges = {
        (None, S.PENDING_MERCHANT),
        (S.PENDING_MERCHANT, S.APPROVED),
        (S.PENDING_MERCHANT, S.REJECTED),
        (S.PENDING_MERCHANT, S.AWAITING_CUSTOMER_INFO),
        (S.AWAITING_CUSTOMER_INFO, S.PENDING_MERCHANT),
        (S.APPROVED, S.AWAITING_RETURN),
        (S.APPROVED, S.REFUNDED),
        (S.AWAITING_RETURN, S.RECEIVED),
        (S.RECEIVED, S.REFUNDED),
        (S.REFUNDED, S.CLOSED),
        (S.REJECTED, S.CLOSED),
        (S.APPROVED, S.CLOSED),
    }
    assert set(ALLOWED_TRANSITIONS) == prd_edges
    assert ALLOWED_TRANSITIONS[(S.APPROVED, S.CLOSED)] == {K.TICKET}


@pytest.mark.parametrize(
    ("kind", "source", "target"),
    [
        (K.REFUND_ONLY, S.APPROVED, S.AWAITING_RETURN),
        (K.RETURN_REFUND, S.APPROVED, S.REFUNDED),
        (K.TICKET, S.APPROVED, S.REFUNDED),
        (K.TICKET, S.APPROVED, S.AWAITING_RETURN),
        (K.RETURN_REFUND, S.APPROVED, S.CLOSED),
        (K.RETURN_REFUND, S.CLOSED, S.PENDING_MERCHANT),
        (K.RETURN_REFUND, S.RECEIVED, S.AWAITING_RETURN),
        (K.RETURN_REFUND, S.PENDING_MERCHANT, S.REFUNDED),
    ],
)
def test_illegal_transitions_are_rejected(
    kind: AfterSaleType, source: AfterSaleState, target: AfterSaleState
) -> None:
    assert not is_allowed_transition(kind, source, target)
