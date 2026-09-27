"""N1 C 前三批迁移的 PostgreSQL 约束验收。"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, text, update
from sqlalchemy.exc import DBAPIError

from app.jobs.rebuild_projections import rebuild_projections
from app.models.analytics import Order, Product
from app.models.events import AfterSaleEvent, FulfillmentEvent, InventoryEvent
from tests.integration._db_asserts import (
    CHECK_VIOLATION,
    GENERATED_ALWAYS,
    NOT_NULL_VIOLATION,
    RAISE_EXCEPTION,
    UNIQUE_VIOLATION,
    assert_sqlstate,
)


def _product(merchant_id, **values):
    return {
        "id": uuid4(),
        "merchant_id": merchant_id,
        "business_date": date(2026, 9, 20),
        "product_code": f"p-{uuid4().hex}",
        "title": "测试商品",
        "category": "测试",
        "price": Decimal("10.00"),
        "status": "ONLINE",
        "listed_at": datetime.now(UTC),
        **values,
    }


def _order(merchant_id, **values):
    return {
        "id": uuid4(),
        "merchant_id": merchant_id,
        "business_date": date(2026, 9, 20),
        "order_no": f"o-{uuid4().hex}",
        "buyer_key": "demo-buyer",
        "order_status": "CREATED",
        "payment_status": "PENDING",
        "fulfillment_status": "NOT_SHIPPED",
        "after_sale_status": "NONE",
        "lifecycle_origin": "V2",
        "total_amount": Decimal("10.00"),
        "paid_amount": Decimal("0.00"),
        "placed_at": datetime.now(UTC),
        **values,
    }


@pytest.mark.asyncio
async def test_product_stock_is_derived_and_cannot_oversell(db_session, merchant_one_id):
    product = _product(merchant_one_id, stock_on_hand=5, stock_reserved=2)
    await db_session.execute(insert(Product).values(product))
    actual = await db_session.scalar(
        text("SELECT stock_available FROM products WHERE id = :id"), {"id": product["id"]}
    )
    assert actual == 3
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            # reserved <= on_hand 也会拒绝负在库；暂时移除它以单独验证此 CHECK。
            await db_session.execute(
                text("ALTER TABLE products DROP CONSTRAINT ck_products_reserved_le_on_hand")
            )
            await db_session.execute(
                insert(Product).values(_product(merchant_one_id, stock_on_hand=-1))
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_products_stock_on_hand_nonneg")
    # pytest.raises 必须包在保存点外面：异常穿出 begin_nested 才会回滚到保存点，
    # 反过来写会在已中止的事务上 RELEASE SAVEPOINT。
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                update(Product).where(Product.id == product["id"]).values(stock_reserved=6)
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_products_reserved_le_on_hand")
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE products SET stock_available = 99 WHERE id = :id"),
                {"id": product["id"]},
            )
    assert_sqlstate(error, GENERATED_ALWAYS)


@pytest.mark.asyncio
async def test_order_projection_is_constrained(db_session, merchant_one_id):
    # 未支付即发货同时违反两条约束，PostgreSQL 按约束名字母序检查，总是先报
    # legacy_status_consistent。在保存点内临时去掉它，才能单独证明 unpaid_not_shipped 生效；
    # DDL 随保存点回滚，约束会恢复。
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("ALTER TABLE orders DROP CONSTRAINT ck_orders_legacy_status_consistent")
            )
            await db_session.execute(
                insert(Order).values(_order(merchant_one_id, fulfillment_status="SHIPPED"))
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_orders_unpaid_not_shipped")
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                insert(Order).values(
                    _order(merchant_one_id, order_status="COMPLETED", payment_status="PAID")
                )
            )
    assert_sqlstate(error, CHECK_VIOLATION, "ck_orders_legacy_status_consistent")
    without_origin = _order(merchant_one_id)
    del without_origin["lifecycle_origin"]
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(insert(Order).values(without_origin))
    assert_sqlstate(error, NOT_NULL_VIOLATION)
    legacy_check = await db_session.scalar(
        text(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = 'ck_orders_legacy_status_consistent'"
        )
    )
    assert legacy_check == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("event_model", [InventoryEvent, FulfillmentEvent, AfterSaleEvent])
async def test_event_ledger_is_append_only_and_deduplicated(
    db_session, merchant_one_id, event_model
):
    table = event_model.__tablename__
    trigger = f"trg_{table}_append_only"
    actual_trigger = await db_session.scalar(
        text("""
            SELECT tgname FROM pg_trigger g JOIN pg_class t ON t.oid = g.tgrelid
            WHERE t.relname = :table AND tgname = :trigger AND NOT tgisinternal
        """),
        {"table": table, "trigger": trigger},
    )
    assert actual_trigger == trigger
    event_id = uuid4()
    values = {
        "id": event_id,
        "merchant_id": merchant_one_id,
        "subject_id": uuid4(),
        "event_type": "STOCK_RECEIVED",
        "occurred_at": datetime.now(UTC),
        "dedupe_key": f"test:{event_id}",
        "payload": {"quantity": 5},
    }
    await db_session.execute(insert(event_model).values(values))
    for statement in (
        update(event_model).where(event_model.id == event_id).values(event_type="X"),
        delete(event_model).where(event_model.id == event_id),
    ):
        with pytest.raises(DBAPIError) as error:
            async with db_session.begin_nested():
                await db_session.execute(statement)
        assert_sqlstate(error, RAISE_EXCEPTION)
        assert table in str(error.value.orig)
    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(insert(event_model).values({**values, "id": uuid4()}))
    assert_sqlstate(error, UNIQUE_VIOLATION, f"uq_{table}_dedupe_key")
    remaining = await db_session.scalar(
        text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": event_id}
    )
    assert remaining == 1


@pytest.mark.asyncio
async def test_projection_rebuild_reports_drift_without_overwriting(db_session, merchant_one_id):
    order = _order(merchant_one_id, order_status="PAID", payment_status="PAID")
    await db_session.execute(insert(Order).values(order))
    await db_session.execute(
        insert(FulfillmentEvent).values(
            {
                "id": uuid4(),
                "merchant_id": merchant_one_id,
                "subject_id": order["id"],
                "event_type": "ORDER_PLACED",
                "occurred_at": order["placed_at"],
                "dedupe_key": f"test:{order['id']}:placed",
                "payload": {"origin": "V2"},
            }
        )
    )
    report = await rebuild_projections(db_session, dry_run=True, merchant_id=merchant_one_id)
    assert report.checked == 1
    assert report.mismatches == 1
    assert {drift.field for drift in report.drift} >= {"payment_status", "order_status"}
    assert (
        await db_session.scalar(
            text("SELECT payment_status FROM orders WHERE id = :id"), {"id": order["id"]}
        )
        == "PAID"
    )
