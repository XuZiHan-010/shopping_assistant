"""WS 只读订单工具的订单事实与归属边界。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import update

from app.core.session import SessionContext, SessionRole
from app.models.analytics import Order
from app.models.events import FulfillmentEvent
from app.tools.customer.orders import GetMyOrderArgs, build_order_tools
from app.tools.errors import FatalToolError
from app.tools.types import ToolContext
from tests.conftest import MERCHANT_ONE_ID, MERCHANT_TWO_ID
from tests.support.merchant_v2 import seed_paid_order, seed_product
from tests.support.trade import bound_context, database_of


def _context(merchant_id=MERCHANT_ONE_ID, buyer_key: str | None = "demo-buyer-1") -> ToolContext:
    session = (
        bound_context(merchant_id, buyer_key)
        if buyer_key is not None
        else SessionContext(
            session_record_id=uuid4(),
            role=SessionRole.CUSTOMER,
            merchant_id=merchant_id,
            buyer_key=None,
            shop_slug="borough-api-100",
        )
    )
    return ToolContext(session=session, conversation_id=str(uuid4()), request_id="ws-order-test")


@pytest.mark.asyncio
async def test_order_tool_returns_recent_events_without_identity(postgres_app: FastAPI) -> None:
    database = database_of(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID, title="测试商品")
    order_id = await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=2)
    base = datetime.now(UTC) - timedelta(hours=7)
    async with database.session() as session:
        for index in range(7):
            session.add(
                FulfillmentEvent(
                    merchant_id=MERCHANT_ONE_ID,
                    subject_id=order_id,
                    event_type="IN_TRANSIT",
                    occurred_at=base + timedelta(hours=index),
                    dedupe_key=f"ws-order-test-{order_id}-{index}",
                    payload={},
                )
            )
        await session.commit()

    (tool,) = build_order_tools(database)
    result = await tool.executor(_context(), GetMyOrderArgs(order_id=str(order_id)))
    payload = result.payload
    assert isinstance(payload, dict)
    assert payload["payment_status"] == "PAID"
    assert payload["fulfillment_status"] == "NOT_SHIPPED"
    assert payload["items"] == [{"name": "—", "quantity": 2}]
    assert len(payload["recent_events"]) == 5
    assert [event["occurred_at"] for event in payload["recent_events"]] == sorted(
        event["occurred_at"] for event in payload["recent_events"]
    )
    assert "buyer_key" not in payload and "merchant_id" not in payload


@pytest.mark.asyncio
async def test_order_tool_rejects_other_customer_shop_guest_and_legacy(
    postgres_app: FastAPI,
) -> None:
    database = database_of(postgres_app)
    product = await seed_product(database, MERCHANT_ONE_ID)
    order_id = await seed_paid_order(database, MERCHANT_ONE_ID, product, quantity=1)
    (tool,) = build_order_tools(database)
    rejected = (
        (_context(buyer_key="other-buyer"), str(order_id)),
        (_context(merchant_id=MERCHANT_TWO_ID), str(order_id)),
        (_context(buyer_key=None), str(order_id)),
        (_context(), "not-a-uuid"),
    )
    for ctx, raw_id in rejected:
        with pytest.raises(FatalToolError) as error:
            await tool.executor(ctx, GetMyOrderArgs(order_id=raw_id))
        assert error.value.gate == "ownership"

    async with database.session() as session:
        await session.execute(
            update(Order).where(Order.id == order_id).values(lifecycle_origin="LEGACY_V1")
        )
        await session.commit()
    with pytest.raises(FatalToolError) as error:
        await tool.executor(_context(), GetMyOrderArgs(order_id=str(order_id)))
    assert error.value.gate == "ownership"
