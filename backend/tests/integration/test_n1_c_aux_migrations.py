"""N1 C 的 M4–M8 持久化约束。只在独立、可丢弃的 PostgreSQL 测试库运行。"""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.session import SessionRole
from app.domain.order_status_mapping import close_reason_from_api, close_reason_to_api
from app.models.after_sales import AfterSale, AfterSaleLine
from app.models.analytics import Order, OrderItem, Product, Refund, SupportTicket
from app.models.base import Base
from app.models.drafts import Draft
from app.models.idempotency import IdempotencyRecord
from app.models.memory_v2 import CustomerMemory, CustomerSignal, DailyBrief, MerchantMemoryFact
from app.models.promotion import Coupon, GuardrailConfig
from app.models.session import AgentSession
from app.schemas.v2.after_sales import AfterSaleState, AfterSaleType
from app.schemas.v2.drafts import DraftState
from app.schemas.v2.merchant_ops import CustomerSignalKind
from app.schemas.v2.trade import CloseReason, FulfillmentStatus, PaymentStatus
from tests.integration._db_asserts import (
    CHECK_VIOLATION,
    NOT_NULL_VIOLATION,
    RAISE_EXCEPTION,
    UNIQUE_VIOLATION,
    assert_sqlstate,
)

NOW = datetime(2026, 9, 22, tzinfo=UTC)


def _check_values(model: type, name: str) -> set[str]:
    check = next(c for c in model.__table__.constraints if c.name == name)
    return {
        part.strip().strip("'")
        for part in check.sqltext.text.split("IN (", 1)[1].split(")", 1)[0].split(",")
    }


def _draft(merchant_id: UUID, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "merchant_id": merchant_id,
        "kind": "RESTOCK",
        "title": "测试补货草稿",
        "target_type": "PRODUCT",
        "target_id": uuid4(),
        "target_version": 1,
        "draft_version": 1,
        "state": "STAGED",
        "payload": {},
        "guardrail_snapshot": {},
        "created_by": "merchant-test",
        "expires_at": NOW + timedelta(days=1),
    }
    values.update(overrides)
    return values


def _coupon(merchant_id: UUID, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "merchant_id": merchant_id,
        "name": "测试优惠券",
        "kind": "FULL_REDUCTION",
        "threshold_amount": Decimal("100.00"),
        "discount_amount": Decimal("10.00"),
        "scope": "ALL",
        "product_ids": [],
        "starts_at": NOW,
        "ends_at": NOW + timedelta(days=1),
        "state": "ACTIVE",
    }
    values.update(overrides)
    return values


def _idem(merchant_id: UUID, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "role": "CUSTOMER",
        "principal_digest": "a" * 64,
        "merchant_id": merchant_id,
        "operation": "shop.orders.create",
        "client_request_id": "same-id",
        "request_digest": "b" * 64,
        "status": "PROCESSING",
    }
    values.update(overrides)
    return values


def test_n1_auxiliary_tables_are_registered() -> None:
    assert {
        "drafts",
        "change_ledger",
        "coupons",
        "guardrail_configs",
        "customer_memories",
        "merchant_memory_facts",
        "merchant_memory_summaries",
        "customer_signals",
        "daily_briefs",
        "after_sales",
        "after_sale_lines",
        "idempotency_records",
    } <= set(Base.metadata.tables)


@pytest.mark.asyncio
async def test_database_enums_equal_frozen_v2_contract(db_session: AsyncSession) -> None:
    async def db_values(table: str, constraint: str) -> set[str]:
        definition = await db_session.scalar(
            text("""
                SELECT pg_get_constraintdef(c.oid)
                FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = :table AND c.conname = :constraint
            """),
            {"table": table, "constraint": constraint},
        )
        assert definition is not None, (table, constraint)
        return set(re.findall(r"'([^']+)'::character varying", definition))

    for model, constraint, expected in (
        (AfterSale, "ck_after_sales_state", {s.value for s in AfterSaleState}),
        (AfterSale, "ck_after_sales_type", {t.value for t in AfterSaleType}),
        (CustomerSignal, "ck_customer_signals_kind", {s.value for s in CustomerSignalKind}),
        (Order, "ck_orders_payment_status", {s.value for s in PaymentStatus}),
        (Order, "ck_orders_fulfillment_status", {s.value for s in FulfillmentStatus}),
        (Draft, "ck_drafts_state", {s.value for s in DraftState}),
        (AgentSession, "ck_agent_sessions_role", {s.value for s in SessionRole}),
    ):
        assert _check_values(model, constraint) == expected
        assert await db_values(model.__tablename__, constraint) == expected

    # 关闭原因存储词汇与 API 有意不同，但必须由显式双向映射穷举对应。
    definition = await db_session.scalar(
        text("""
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'orders' AND c.conname = 'ck_orders_legacy_status_consistent'
        """)
    )
    assert definition is not None
    stored_reasons = set(re.findall(r"\(close_reason\)::text\s*=\s*'([^']+)'", definition))
    assert stored_reasons == {close_reason_from_api(reason) for reason in CloseReason}
    assert {close_reason_to_api(reason) for reason in stored_reasons} == {
        reason.value for reason in CloseReason
    }


@pytest.mark.asyncio
async def test_draft_rejects_approved_state_and_terminal_reentry(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    with pytest.raises(DBAPIError) as invalid:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(Draft).values(**_draft(merchant_one_id, state="APPROVED"))
            )
    assert_sqlstate(invalid, CHECK_VIOLATION, "ck_drafts_state")

    draft_id = (
        await db_session.execute(
            insert(Draft).values(**_draft(merchant_one_id, state="APPLIED")).returning(Draft.id)
        )
    ).scalar_one()
    with pytest.raises(DBAPIError) as reentry:
        async with db_session.begin_nested():
            await db_session.execute(
                update(Draft).where(Draft.id == draft_id).values(state="STAGED")
            )
    assert_sqlstate(reentry, RAISE_EXCEPTION)


@pytest.mark.asyncio
async def test_coupon_window_and_discount_guardrail_are_database_checks(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    with pytest.raises(DBAPIError) as window:
        async with db_session.begin_nested():
            await db_session.execute(insert(Coupon).values(**_coupon(merchant_one_id, ends_at=NOW)))
    assert_sqlstate(window, CHECK_VIOLATION, "ck_coupons_time_window")

    with pytest.raises(DBAPIError) as ceiling:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(GuardrailConfig).values(
                    merchant_id=merchant_one_id,
                    max_discount_rate=Decimal("0.21"),
                    max_price_change_rate=Decimal("0.10"),
                    updated_by="merchant-test",
                )
            )
    assert_sqlstate(ceiling, CHECK_VIOLATION, "ck_guardrail_configs_max_discount_rate")


@pytest.mark.asyncio
async def test_memory_isolation_source_and_daily_brief_uniqueness(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    with pytest.raises(DBAPIError) as merchant:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(CustomerMemory).values(
                    merchant_id=None,
                    buyer_key="buyer-one",
                    key="preference",
                    value="blue",
                    category="PREFERENCE",
                    last_confirmed_at=NOW,
                )
            )
    assert_sqlstate(merchant, NOT_NULL_VIOLATION)

    with pytest.raises(DBAPIError) as buyer:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(CustomerMemory).values(
                    merchant_id=merchant_one_id,
                    buyer_key=None,
                    key="preference",
                    value="blue",
                    category="PREFERENCE",
                    last_confirmed_at=NOW,
                )
            )
    assert_sqlstate(buyer, NOT_NULL_VIOLATION)

    with pytest.raises(DBAPIError) as source:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(MerchantMemoryFact).values(
                    merchant_id=merchant_one_id,
                    content="事实",
                    source_ref=None,
                    category="OPERATIONS",
                )
            )
    assert_sqlstate(source, NOT_NULL_VIOLATION)

    brief = {
        "merchant_id": merchant_one_id,
        "business_date": date(2026, 9, 22),
        "brief_version": 1,
        "payload": {},
        "generated_at": NOW,
    }
    await db_session.execute(insert(DailyBrief).values(**brief))
    with pytest.raises(DBAPIError) as duplicate:
        async with db_session.begin_nested():
            await db_session.execute(insert(DailyBrief).values(**brief))
    assert_sqlstate(duplicate, UNIQUE_VIOLATION, "uq_daily_briefs_merchant_date")


@pytest.mark.asyncio
async def test_idempotency_domain_isolates_principal_and_operation(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    await db_session.execute(insert(IdempotencyRecord).values(**_idem(merchant_one_id)))
    await db_session.execute(
        insert(IdempotencyRecord).values(**_idem(merchant_one_id, principal_digest="c" * 64))
    )
    await db_session.execute(
        insert(IdempotencyRecord).values(**_idem(merchant_one_id, operation="shop.orders.pay"))
    )
    with pytest.raises(DBAPIError) as duplicate:
        async with db_session.begin_nested():
            await db_session.execute(insert(IdempotencyRecord).values(**_idem(merchant_one_id)))
    assert_sqlstate(duplicate, UNIQUE_VIOLATION, "uq_idempotency_records_domain")


@pytest.mark.asyncio
async def test_after_sale_checks_ticket_uniqueness_and_legacy_null_link(
    db_session: AsyncSession, merchant_one_id: UUID
) -> None:
    product_id = (
        await db_session.execute(
            insert(Product)
            .values(
                merchant_id=merchant_one_id,
                business_date=date(2026, 9, 22),
                product_code="after-sale-product",
                title="商品",
                category="测试",
                price=Decimal("10.00"),
                status="ONLINE",
                listed_at=NOW,
            )
            .returning(Product.id)
        )
    ).scalar_one()
    order_id = (
        await db_session.execute(
            insert(Order)
            .values(
                merchant_id=merchant_one_id,
                business_date=date(2026, 9, 22),
                order_no="after-sale-order",
                buyer_key="buyer-one",
                order_status="COMPLETED",
                payment_status="PAID",
                fulfillment_status="DELIVERED",
                lifecycle_origin="V2",
                total_amount=Decimal("10.00"),
                paid_amount=Decimal("10.00"),
                placed_at=NOW,
                paid_at=NOW,
            )
            .returning(Order.id)
        )
    ).scalar_one()
    item_id = (
        await db_session.execute(
            insert(OrderItem)
            .values(
                merchant_id=merchant_one_id,
                business_date=date(2026, 9, 22),
                order_id=order_id,
                product_id=product_id,
                quantity=1,
                item_amount=Decimal("10.00"),
                unit_price=Decimal("10.00"),
                discount_amount=Decimal("0.00"),
                line_total=Decimal("10.00"),
            )
            .returning(OrderItem.id)
        )
    ).scalar_one()

    sale = {
        "merchant_id": merchant_one_id,
        "buyer_key": "buyer-one",
        "order_id": order_id,
        "after_sale_type": "TICKET",
        "state": "PENDING_MERCHANT",
        "reason": "需要帮助",
        "refund_amount": None,
    }
    with pytest.raises(DBAPIError) as state:
        async with db_session.begin_nested():
            await db_session.execute(insert(AfterSale).values(**(sale | {"state": "INVALID"})))
    assert_sqlstate(state, CHECK_VIOLATION, "ck_after_sales_state")
    sale_id = (
        await db_session.execute(insert(AfterSale).values(**sale).returning(AfterSale.id))
    ).scalar_one()

    ticket = {
        "merchant_id": merchant_one_id,
        "business_date": date(2026, 9, 22),
        "ticket_no": "ticket-one",
        "order_id": order_id,
        "after_sale_id": sale_id,
        "ticket_status": "OPEN",
        "ticket_reason": "需要帮助",
        "opened_at": NOW,
    }
    await db_session.execute(insert(SupportTicket).values(**ticket))
    with pytest.raises(DBAPIError) as duplicate_ticket:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(SupportTicket).values(**(ticket | {"ticket_no": "ticket-two"}))
            )
    assert_sqlstate(duplicate_ticket, UNIQUE_VIOLATION, "uq_support_tickets_after_sale_id")

    with pytest.raises(DBAPIError) as quantity:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(AfterSaleLine).values(
                    after_sale_id=sale_id,
                    order_item_id=item_id,
                    quantity=0,
                    refund_amount=Decimal("0.00"),
                )
            )
    assert_sqlstate(quantity, CHECK_VIOLATION, "ck_after_sale_lines_quantity")

    with pytest.raises(DBAPIError) as negative_refund:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(AfterSaleLine).values(
                    after_sale_id=sale_id,
                    order_item_id=item_id,
                    quantity=1,
                    refund_amount=Decimal("-0.01"),
                )
            )
    assert_sqlstate(negative_refund, CHECK_VIOLATION, "ck_after_sale_lines_refund_amount")

    legacy_ticket_id = (
        await db_session.execute(
            insert(SupportTicket)
            .values(**(ticket | {"ticket_no": "legacy-ticket", "after_sale_id": None}))
            .returning(SupportTicket.id)
        )
    ).scalar_one()
    legacy_ticket = await db_session.get(SupportTicket, legacy_ticket_id)
    assert legacy_ticket is not None and legacy_ticket.after_sale_id is None

    legacy_refund_id = (
        await db_session.execute(
            insert(Refund)
            .values(
                merchant_id=merchant_one_id,
                business_date=date(2026, 9, 22),
                order_item_id=item_id,
                refund_amount=Decimal("10.00"),
                refund_reason="历史退款",
                refund_status="REFUNDED",
                refunded_at=NOW,
            )
            .returning(Refund.id)
        )
    ).scalar_one()
    legacy_refund = await db_session.get(Refund, legacy_refund_id)
    assert legacy_refund is not None and legacy_refund.after_sale_id is None
