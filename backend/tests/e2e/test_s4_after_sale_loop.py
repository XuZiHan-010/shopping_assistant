"""S4：顾客确认、商家草稿审批、补充、收货回补和退款共享同一售后事实。"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.models.after_sales import AfterSale
from app.models.analytics import Order, Product, Refund, ReturnRecord
from app.models.events import FulfillmentEvent, InventoryEvent
from app.schemas.v2.drafts import DraftKind
from app.services.v2.drafts import DraftRepository
from tests.conftest import MERCHANT_ONE_AUTH, MERCHANT_ONE_ID
from tests.support.merchant_v2 import merchant_session_headers, seed_paid_order, seed_product
from tests.support.trade import SHOP, bound_customer, database_of

pytestmark = pytest.mark.integration


async def approve(
    app: FastAPI, client: AsyncClient, headers: dict[str, str],
    sale_id: str, decision: str, *, sellable: bool | None = None,
) -> dict[str, object]:
    database = database_of(app)
    async with database.session() as session:
        sale = await session.get(AfterSale, UUID(sale_id))
        assert sale is not None
        payload: dict[str, object] = {"decision": decision}
        if sellable is not None:
            payload["sellable"] = sellable
        draft = await DraftRepository(session).stage(
            merchant_id=MERCHANT_ONE_ID, kind=DraftKind.AFTER_SALE_DECISION,
            title=f"售后决定：{decision}", target_type="AFTER_SALE",
            target_id=sale.id, target_version=sale.state_version,
            payload=payload, guardrail_snapshot={}, created_by="AGENT",
            now=datetime.now(UTC),
        )
        draft_id = str(draft.id)
        await session.commit()
    detail = await client.get(f"/api/v2/merchant/drafts/{draft_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    result = await client.post(
        f"/api/v2/merchant/drafts/{draft_id}/apply", headers=headers,
        json={
            "client_request_id": f"apply-{draft_id}", "draft_version": body["draft_version"],
            "target_version": body["target_version"],
            "approval_evidence": body["approval_evidence"],
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.asyncio
async def test_s4_return_refund_end_to_end(
    postgres_app: FastAPI, postgres_client: AsyncClient
) -> None:
    database = database_of(postgres_app)
    product_id = await seed_product(database, MERCHANT_ONE_ID, on_hand=40)
    order_id = await seed_paid_order(database, MERCHANT_ONE_ID, product_id, quantity=1)
    now = datetime.now(UTC)
    async with database.session() as session:
        order = await session.get(Order, order_id)
        assert order is not None
        order.order_status = "COMPLETED"
        order.fulfillment_status = "DELIVERED"
        session.add(FulfillmentEvent(
            merchant_id=MERCHANT_ONE_ID, subject_id=order_id,
            event_type="DELIVERED", occurred_at=now,
            dedupe_key=f"test-s4-delivered:{order_id}", payload={},
        ))
        await session.commit()

    customer = await bound_customer(
        postgres_client, postgres_app, buyer_key="demo-buyer-1", shop_slug=SHOP
    )
    merchant = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    payload = {
        "client_request_id": "s4-return", "order_id": str(order_id),
        "after_sale_type": "RETURN_REFUND", "reason": "商品破损",
    }
    preview = await postgres_client.post("/api/v2/shop/after-sales", headers=customer, json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"]["estimated_refund_cents"] == 10000
    created = await postgres_client.post("/api/v2/shop/after-sales", headers=customer, json={
        **payload, "confirmation_token": preview.json()["confirmation_token"]
    })
    assert created.status_code == 201, created.text
    sale_id = created.json()["id"]

    queue = await postgres_client.get("/api/v2/merchant/after-sales", headers=merchant)
    assert queue.status_code == 200 and queue.json()["items"][0]["id"] == sale_id
    signal = await postgres_client.get("/api/v2/merchant/customer-signals", headers=merchant)
    assert signal.json()["items"][0]["kind"] == "RETURN_REQUESTS"

    await approve(postgres_app, postgres_client, merchant, sale_id, "REQUEST_INFO")
    supplement = await postgres_client.post(
        f"/api/v2/shop/after-sales/{sale_id}/supplements", headers=customer,
        json={"client_request_id": "s4-supplement", "note": "包装和商品均已破损"},
    )
    assert supplement.status_code == 200 and supplement.json()["state"] == "PENDING_MERCHANT"
    await approve(postgres_app, postgres_client, merchant, sale_id, "APPROVE")
    await approve(postgres_app, postgres_client, merchant, sale_id, "RECEIVE", sellable=True)
    await approve(postgres_app, postgres_client, merchant, sale_id, "REFUND")

    detail = await postgres_client.get(f"/api/v2/shop/after-sales/{sale_id}", headers=customer)
    assert detail.status_code == 200, detail.text
    assert detail.json()["state"] == "CLOSED"
    assert detail.json()["refund_amount_cents"] == 10000
    assert [event["to_state"] for event in detail.json()["events"]][-2:] == ["REFUNDED", "CLOSED"]
    async with database.session() as session:
        refund = await session.scalar(select(Refund).where(Refund.after_sale_id == UUID(sale_id)))
        received = await session.scalar(select(ReturnRecord).where(
            ReturnRecord.after_sale_id == UUID(sale_id)
        ))
        restock = await session.scalar(select(InventoryEvent).where(
            InventoryEvent.event_type == "RETURN_RESTOCK",
            InventoryEvent.subject_id == product_id,
        ))
        product = await session.get(Product, product_id)
        assert refund is not None and refund.refund_amount == Decimal("100.00")
        assert received is not None and restock is not None
        assert product is not None and product.stock_on_hand == 41
