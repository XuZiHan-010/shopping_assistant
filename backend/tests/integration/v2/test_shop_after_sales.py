"""顾客售后两阶段提交的证据、幂等和金额边界。"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select

import app.api.routes.v2.shop_after_sales as shop_after_sales_route
from app.core.session import SessionContext, SessionRole
from app.models.after_sales import AfterSale
from app.models.analytics import SupportTicket
from app.models.operations import OperationEvidenceNonce
from app.schemas.v2.after_sales import AfterSaleActor, AfterSaleState
from app.services.v2.after_sale_machine import transition
from app.tools.merchant.after_sale import GetAfterSaleArgs, build_after_sale_tools
from app.tools.types import ToolContext
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product
from tests.support.trade import SHOP, bound_customer, database_of

pytestmark = pytest.mark.integration
PATH = "/api/v2/shop/after-sales"


async def setup_order(app: FastAPI, client: AsyncClient) -> tuple[dict[str, str], UUID]:
    database = database_of(app)
    product_id = await seed_product(database, MERCHANT_ONE_ID)
    order_id = await seed_paid_order(database, MERCHANT_ONE_ID, product_id, quantity=1)
    headers = await bound_customer(client, app, buyer_key="demo-buyer-1", shop_slug=SHOP)
    return headers, order_id


def request(order_id: UUID, *, key: str = "sale-1", token: str | None = None) -> dict[str, object]:
    return {
        "client_request_id": key,
        "order_id": str(order_id),
        "after_sale_type": "REFUND_ONLY",
        "reason": "商品不合适",
        **({} if token is None else {"confirmation_token": token}),
    }


@pytest.mark.asyncio
async def test_challenge_writes_no_sale_then_confirm_creates_once(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, order_id = await setup_order(postgres_app, postgres_client)
    database = database_of(postgres_app)

    first = await postgres_client.post(PATH, headers=headers, json=request(order_id))
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["summary"]["estimated_refund_cents"] == 10000
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(AfterSale)) == 0
        assert await session.scalar(select(func.count()).select_from(OperationEvidenceNonce)) == 1

    confirmed = request(order_id, token=first.json()["confirmation_token"])
    second = await postgres_client.post(PATH, headers=headers, json=confirmed)
    assert second.status_code == 201, second.text
    assert second.json()["state"] == "PENDING_MERCHANT"
    retry = await postgres_client.post(PATH, headers=headers, json=confirmed)
    assert retry.status_code == 201 and retry.json() == second.json()
    async with database.session() as session:
        assert await session.scalar(select(func.count()).select_from(AfterSale)) == 1


@pytest.mark.asyncio
async def test_ticket_business_date_is_business_day_across_utc_midnight(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UTC 9/24 20:00 = 上海 9/25 04:00：售后工单记在业务日 9/25。"""

    cross_day = datetime(2026, 9, 24, 20, tzinfo=UTC)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def, override]
            return cross_day if tz is None else cross_day.astimezone(tz)

    database = database_of(postgres_app)
    product_id = await seed_product(database, MERCHANT_ONE_ID, now=cross_day - timedelta(days=2))
    order_id = await seed_paid_order(
        database, MERCHANT_ONE_ID, product_id, quantity=1, now=cross_day
    )
    headers = await bound_customer(
        postgres_client, postgres_app, buyer_key="demo-buyer-1", shop_slug=SHOP
    )
    monkeypatch.setattr(shop_after_sales_route, "datetime", _Frozen)

    first = await postgres_client.post(PATH, headers=headers, json=request(order_id))
    assert first.status_code == 200, first.text
    confirmed = request(order_id, token=first.json()["confirmation_token"])
    second = await postgres_client.post(PATH, headers=headers, json=confirmed)
    assert second.status_code == 201, second.text
    async with database.session() as session:
        ticket = await session.scalar(
            select(SupportTicket).where(SupportTicket.order_id == order_id)
        )
    assert ticket is not None and ticket.business_date == date(2026, 9, 25)


@pytest.mark.asyncio
async def test_consumed_confirmation_with_new_request_id_uses_confirmation_error(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, order_id = await setup_order(postgres_app, postgres_client)
    challenge = await postgres_client.post(PATH, headers=headers, json=request(order_id))
    assert challenge.status_code == 200
    token = challenge.json()["confirmation_token"]
    first = await postgres_client.post(PATH, headers=headers, json=request(order_id, token=token))
    assert first.status_code == 201

    replay = await postgres_client.post(
        PATH, headers=headers, json=request(order_id, key="new-request", token=token)
    )
    assert replay.status_code == 422
    assert replay.json()["code"] == "CONFIRMATION_REQUIRED"
    async with database_of(postgres_app).session() as session:
        assert await session.scalar(select(func.count()).select_from(AfterSale)) == 1


@pytest.mark.asyncio
async def test_chat_preview_matches_confirmation_after_partial_refund(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    from decimal import Decimal

    from app.models.analytics import OrderItem, Refund
    from app.tools.customer.after_sale import PrepareAfterSaleArgs, build_after_sale_tools

    headers, order_id = await setup_order(postgres_app, postgres_client)
    database = database_of(postgres_app)
    now = datetime.now(UTC)
    async with database.session() as session:
        item = await session.scalar(select(OrderItem).where(OrderItem.order_id == order_id))
        assert item is not None
        session.add(
            Refund(
                merchant_id=MERCHANT_ONE_ID,
                business_date=now.date(),
                order_item_id=item.id,
                refund_amount=Decimal("30.00"),
                refund_reason="PREVIOUS",
                refund_status="REFUNDED",
                refunded_at=now,
            )
        )
        await session.commit()
    tool = next(
        spec for spec in build_after_sale_tools(database) if spec.name == "prepare_after_sale"
    )
    ctx = ToolContext(
        session=SessionContext(
            session_record_id=uuid4(),
            role=SessionRole.CUSTOMER,
            merchant_id=MERCHANT_ONE_ID,
            buyer_key="demo-buyer-1",
            shop_slug=SHOP,
        ),
        conversation_id=str(uuid4()),
        request_id="partial-refund-preview",
    )
    preview = await tool.executor(
        ctx, PrepareAfterSaleArgs(order_id=str(order_id), after_sale_type="REFUND_ONLY")
    )
    challenge = await postgres_client.post(PATH, headers=headers, json=request(order_id))
    assert challenge.status_code == 200
    assert preview.payload["estimated_refund_cents"] == 7000
    assert (
        preview.payload["estimated_refund_cents"]
        == challenge.json()["summary"]["estimated_refund_cents"]
    )


@pytest.mark.asyncio
async def test_two_confirmations_for_same_order_cannot_create_parallel_sales(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, order_id = await setup_order(postgres_app, postgres_client)
    first = request(order_id, key="parallel-sale-a")
    second = request(order_id, key="parallel-sale-b")
    a = await postgres_client.post(PATH, headers=headers, json=first)
    b = await postgres_client.post(PATH, headers=headers, json=second)
    assert a.status_code == b.status_code == 200
    results = await asyncio.gather(
        postgres_client.post(
            PATH,
            headers=headers,
            json={**first, "confirmation_token": a.json()["confirmation_token"]},
        ),
        postgres_client.post(
            PATH,
            headers=headers,
            json={**second, "confirmation_token": b.json()["confirmation_token"]},
        ),
    )
    assert sorted(response.status_code for response in results) == [201, 422]
    assert (
        next(response for response in results if response.status_code == 422).json()["code"]
        == "GUARDRAIL_REJECTED"
    )
    async with database_of(postgres_app).session() as session:
        assert await session.scalar(select(func.count()).select_from(AfterSale)) == 1


@pytest.mark.asyncio
async def test_summary_unavailable_is_frozen_and_signal_is_derived_once(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, order_id = await setup_order(postgres_app, postgres_client)
    payload = {**request(order_id), "include_conversation_summary": True}
    challenge = await postgres_client.post(PATH, headers=headers, json=payload)
    assert challenge.status_code == 200, challenge.text
    assert challenge.json()["summary"]["conversation_summary_status"] == "UNAVAILABLE"
    confirmed = await postgres_client.post(
        PATH,
        headers=headers,
        json={**payload, "confirmation_token": challenge.json()["confirmation_token"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    sale_id = confirmed.json()["id"]
    detail = await postgres_client.get(f"{PATH}/{sale_id}", headers=headers)
    assert detail.json()["conversation_summary_shared"] is False

    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    merchant_detail = await postgres_client.get(
        f"/api/v2/merchant/after-sales/{sale_id}", headers=merchant
    )
    assert merchant_detail.status_code == 200
    assert merchant_detail.json()["conversation_summary"]["status"] == "UNAVAILABLE"
    signals = await postgres_client.get("/api/v2/merchant/customer-signals", headers=merchant)
    assert signals.status_code == 200, signals.text
    assert len(signals.json()["items"]) == 1
    assert signals.json()["items"][0]["count"] == 1
    retry = await postgres_client.post(
        PATH,
        headers=headers,
        json={**payload, "confirmation_token": challenge.json()["confirmation_token"]},
    )
    assert retry.status_code == 201
    signals_again = await postgres_client.get("/api/v2/merchant/customer-signals", headers=merchant)
    assert signals_again.json()["items"][0]["count"] == 1
    signal_id = signals_again.json()["items"][0]["id"]
    ignore_path = f"/api/v2/merchant/customer-signals/{signal_id}/ignore"
    missing_reason = await postgres_client.post(
        ignore_path, headers=merchant, json={"client_request_id": "ignore-1"}
    )
    assert missing_reason.status_code == 422
    ignored = await postgres_client.post(
        ignore_path, headers=merchant, json={"client_request_id": "ignore-1", "reason": "已跟进"}
    )
    assert ignored.status_code == 200 and ignored.json()["is_ignored"] is True
    assert (
        ignored.json()
        == (
            await postgres_client.post(
                ignore_path,
                headers=merchant,
                json={"client_request_id": "ignore-1", "reason": "已跟进"},
            )
        ).json()
    )
    hidden = await postgres_client.get("/api/v2/merchant/customer-signals", headers=merchant)
    assert hidden.json()["items"] == []
    visible = await postgres_client.get(
        "/api/v2/merchant/customer-signals?include_ignored=true", headers=merchant
    )
    assert visible.json()["items"][0]["id"] == signal_id


@pytest.mark.asyncio
async def test_token_cannot_change_order_and_client_cannot_set_amount(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, order_id = await setup_order(postgres_app, postgres_client)
    token = (await postgres_client.post(PATH, headers=headers, json=request(order_id))).json()[
        "confirmation_token"
    ]
    other = await seed_paid_order(
        database_of(postgres_app),
        MERCHANT_ONE_ID,
        await seed_product(database_of(postgres_app), MERCHANT_ONE_ID),
        quantity=1,
    )
    changed = await postgres_client.post(PATH, headers=headers, json=request(other, token=token))
    assert changed.status_code == 422 and changed.json()["code"] == "CONFIRMATION_REQUIRED"
    injected = await postgres_client.post(
        PATH, headers=headers, json={**request(order_id), "refund_amount_cents": 1}
    )
    assert injected.status_code == 422 and injected.json()["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
async def test_reason_is_redacted_in_preview_and_both_details(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    headers, order_id = await setup_order(postgres_app, postgres_client)
    payload = {**request(order_id), "reason": "电话 13800138000，商品破损"}
    preview = await postgres_client.post(PATH, headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert "13800138000" not in preview.json()["summary"]["reason"]
    created = await postgres_client.post(
        PATH,
        headers=headers,
        json={**payload, "confirmation_token": preview.json()["confirmation_token"]},
    )
    assert created.status_code == 201, created.text
    sale_id = created.json()["id"]
    customer = await postgres_client.get(f"{PATH}/{sale_id}", headers=headers)
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    merchant_detail = await postgres_client.get(
        f"/api/v2/merchant/after-sales/{sale_id}", headers=merchant
    )
    assert "13800138000" not in customer.json()["reason"]
    assert customer.json()["reason"] == merchant_detail.json()["reason"]


async def confirmed_sale(app: FastAPI, client: AsyncClient) -> tuple[dict[str, str], str]:
    headers, order_id = await setup_order(app, client)
    challenge = await client.post(PATH, headers=headers, json=request(order_id))
    assert challenge.status_code == 200, challenge.text
    created = await client.post(
        PATH,
        headers=headers,
        json=request(order_id, token=challenge.json()["confirmation_token"]),
    )
    assert created.status_code == 201, created.text
    return headers, created.json()["id"]


@pytest.mark.asyncio
async def test_customer_only_sees_own_sale_and_detail_has_events(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    owner, sale_id = await confirmed_sale(postgres_app, postgres_client)
    own_list = await postgres_client.get(PATH, headers=owner)
    assert own_list.status_code == 200, own_list.text
    assert [item["id"] for item in own_list.json()["items"]] == [sale_id]
    own_detail = await postgres_client.get(f"{PATH}/{sale_id}", headers=owner)
    assert own_detail.status_code == 200, own_detail.text
    assert own_detail.json()["events"][0]["actor"] == "CUSTOMER"
    assert "buyer_alias" not in own_detail.json()

    other = await bound_customer(
        postgres_client, postgres_app, buyer_key="demo-buyer-2", shop_slug=SHOP
    )
    denied = await postgres_client.get(f"{PATH}/{sale_id}", headers=other)
    missing = await postgres_client.get(f"{PATH}/{UUID(int=8)}", headers=other)
    assert denied.status_code == missing.status_code == 403
    assert {key: value for key, value in denied.json().items() if key != "request_id"} == {
        key: value for key, value in missing.json().items() if key != "request_id"
    }


@pytest.mark.asyncio
async def test_merchant_detail_is_aliased_and_audited(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _, sale_id = await confirmed_sale(postgres_app, postgres_client)
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    path = f"/api/v2/merchant/after-sales/{sale_id}"
    for expected_count in (1, 2):
        response = await postgres_client.get(path, headers=merchant)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["buyer_alias"] and "buyer_key" not in body
        assert "audit_id" not in body and "viewed_audit_id" not in body
        async with database_of(postgres_app).session() as session:
            from app.models.operations import AuditLog

            count = await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.event_type == "AFTER_SALE_SUMMARY_VIEWED",
                    AuditLog.resource_id == sale_id,
                )
            )
        assert count == expected_count


@pytest.mark.asyncio
async def test_merchant_detail_tool_audits_before_exposing_summary(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    _, sale_id = await confirmed_sale(postgres_app, postgres_client)
    database = database_of(postgres_app)
    tools = {
        tool.name: tool
        for tool in build_after_sale_tools(
            database, alias_secret=b"integration-alias-secret-0123456789"
        )
    }
    ctx = ToolContext(
        session=SessionContext(
            session_record_id=uuid4(),
            role=SessionRole.MERCHANT,
            merchant_id=MERCHANT_ONE_ID,
            buyer_key=None,
            shop_slug=None,
        ),
        conversation_id="test-conversation",
        request_id="test-tool-summary-view",
    )
    output = await tools["get_after_sale"].executor(ctx, GetAfterSaleArgs(after_sale_id=sale_id))
    assert "buyer_key" not in str(output.payload)
    async with database.session() as session:
        from app.models.operations import AuditLog

        audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.event_type == "AFTER_SALE_SUMMARY_VIEWED",
                AuditLog.resource_id == sale_id,
                AuditLog.request_id == "test-tool-summary-view",
            )
        )
    assert audit is not None


@pytest.mark.asyncio
async def test_supplement_requires_requested_state_and_is_idempotent_and_redacted(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    owner, sale_id = await confirmed_sale(postgres_app, postgres_client)
    path = f"{PATH}/{sale_id}/supplements"
    payload = {"client_request_id": "supp-1", "note": "电话 13800138000，商品有异响"}
    premature = await postgres_client.post(path, headers=owner, json=payload)
    assert premature.status_code == 409

    database = database_of(postgres_app)
    async with database.session() as session:
        await transition(
            session,
            merchant_id=MERCHANT_ONE_ID,
            after_sale_id=UUID(sale_id),
            target=AfterSaleState.AWAITING_CUSTOMER_INFO,
            actor=AfterSaleActor.MERCHANT,
            now=datetime.now(UTC),
        )
        await session.commit()
    sent = await postgres_client.post(path, headers=owner, json=payload)
    assert sent.status_code == 200, sent.text
    assert sent.json()["state"] == "PENDING_MERCHANT"
    replay = await postgres_client.post(path, headers=owner, json=payload)
    assert replay.status_code == 200 and replay.json() == sent.json()
    changed = await postgres_client.post(
        path, headers=owner, json={**payload, "note": "另一段说明"}
    )
    assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    detail = (await postgres_client.get(f"{PATH}/{sale_id}", headers=owner)).json()
    assert len(detail["supplements"]) == 1
    assert "13800138000" not in detail["supplements"][0]["note"]
    assert detail["events"][-1]["actor"] == "CUSTOMER"
