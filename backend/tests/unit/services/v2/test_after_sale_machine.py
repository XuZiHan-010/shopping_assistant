"""状态迁移的类型、触发方和系统续跳组合。"""

import pytest

from app.schemas.v2.after_sales import AfterSaleActor as A
from app.schemas.v2.after_sales import AfterSaleState as S
from app.schemas.v2.after_sales import AfterSaleType as K
from app.services.v2.after_sale_machine import IllegalTransition, plan_transition


@pytest.mark.parametrize(
    "kind,target,expected",
    [
        (K.RETURN_REFUND, S.APPROVED, [(S.APPROVED, A.MERCHANT), (S.AWAITING_RETURN, A.SYSTEM)]),
        (K.REFUND_ONLY, S.APPROVED, [(S.APPROVED, A.MERCHANT)]),
        (K.TICKET, S.APPROVED, [(S.APPROVED, A.MERCHANT), (S.CLOSED, A.SYSTEM)]),
        (K.RETURN_REFUND, S.REJECTED, [(S.REJECTED, A.MERCHANT), (S.CLOSED, A.SYSTEM)]),
    ],
)
def test_decision_plans_required_system_follow_on(
    kind: K, target: S, expected: list[tuple[S, A]]
) -> None:
    assert plan_transition(kind, S.PENDING_MERCHANT, target, actor=A.MERCHANT) == expected


def test_refund_closes_in_same_plan() -> None:
    assert plan_transition(K.RETURN_REFUND, S.RECEIVED, S.REFUNDED, actor=A.MERCHANT) == [
        (S.REFUNDED, A.MERCHANT),
        (S.CLOSED, A.SYSTEM),
    ]


@pytest.mark.parametrize("kind", list(K))
def test_system_hop_cannot_be_requested_directly(kind: K) -> None:
    for source in S:
        with pytest.raises(IllegalTransition):
            plan_transition(kind, source, S.CLOSED, actor=A.SYSTEM)


def test_customer_supplement_is_only_customer_trigger() -> None:
    assert plan_transition(
        K.TICKET, S.AWAITING_CUSTOMER_INFO, S.PENDING_MERCHANT, actor=A.CUSTOMER
    ) == [(S.PENDING_MERCHANT, A.CUSTOMER)]
    with pytest.raises(IllegalTransition):
        plan_transition(K.TICKET, S.AWAITING_CUSTOMER_INFO, S.PENDING_MERCHANT, actor=A.MERCHANT)


def test_information_request_limit_is_checked_before_hop() -> None:
    assert plan_transition(
        K.RETURN_REFUND,
        S.PENDING_MERCHANT,
        S.AWAITING_CUSTOMER_INFO,
        actor=A.MERCHANT,
        prior_information_requests=46,
    ) == [(S.AWAITING_CUSTOMER_INFO, A.MERCHANT)]
    with pytest.raises(IllegalTransition):
        plan_transition(
            K.RETURN_REFUND,
            S.PENDING_MERCHANT,
            S.AWAITING_CUSTOMER_INFO,
            actor=A.MERCHANT,
            prior_information_requests=47,
        )


def test_ticket_cannot_receive_return_or_refund_transition() -> None:
    for source, target in ((S.APPROVED, S.AWAITING_RETURN), (S.APPROVED, S.REFUNDED)):
        with pytest.raises(IllegalTransition):
            plan_transition(K.TICKET, source, target, actor=A.MERCHANT)


# 从 PRD §7.2 的外部触发方列表独立列出合法首跳；系统续跳只能由状态机自行追加。
_EXTERNAL_HOPS = (
    {(kind, None, S.PENDING_MERCHANT, A.CUSTOMER) for kind in K}
    | {
        (kind, S.PENDING_MERCHANT, target, A.MERCHANT)
        for kind in K
        for target in (S.APPROVED, S.REJECTED, S.AWAITING_CUSTOMER_INFO)
    }
    | {(kind, S.AWAITING_CUSTOMER_INFO, S.PENDING_MERCHANT, A.CUSTOMER) for kind in K}
    | {
        (K.RETURN_REFUND, S.AWAITING_RETURN, S.RECEIVED, A.MERCHANT),
        (K.RETURN_REFUND, S.RECEIVED, S.REFUNDED, A.MERCHANT),
        (K.REFUND_ONLY, S.APPROVED, S.REFUNDED, A.MERCHANT),
    }
)


@pytest.mark.parametrize("kind", list(K))
@pytest.mark.parametrize("source", [None, *S])
@pytest.mark.parametrize("target", list(S))
@pytest.mark.parametrize("actor", list(A))
def test_transition_complement_rejects_every_other_external_request(
    kind: K, source: S | None, target: S, actor: A
) -> None:
    candidate = (kind, source, target, actor)
    if candidate in _EXTERNAL_HOPS:
        assert plan_transition(kind, source, target, actor=actor, prior_information_requests=0)[
            0
        ] == (target, actor)
    else:
        with pytest.raises(IllegalTransition):
            plan_transition(kind, source, target, actor=actor, prior_information_requests=0)
