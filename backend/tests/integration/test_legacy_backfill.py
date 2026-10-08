"""冻结的 v1 状态映射及真实历史行回填。"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import DBAPIError

from app.domain.order_status_mapping import (
    FROM_LEGACY_TABLE,
    LEGACY_ORDER_STATUSES,
    from_legacy_status,
    to_legacy_status,
)
from app.jobs.rebuild_projections import _expected
from tests.integration._db_asserts import RAISE_EXCEPTION, assert_sqlstate
from tests.postgres import alembic_config

PRE_M2 = "20260922_0017"
M3 = "20260922_0019"


def test_legacy_status_roundtrip_is_identity():
    for status in LEGACY_ORDER_STATUSES:
        assert to_legacy_status(*from_legacy_status(status)) == status


def test_frozen_migration_case_table_matches_domain_mapping():
    path = (
        Path(__file__).parents[2] / "migrations/versions/20260922_0018_order_projection_snapshot.py"
    )
    spec = spec_from_file_location("m2_order_projection", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._FROM_LEGACY_TABLE == FROM_LEGACY_TABLE


def test_legacy_rebuild_uses_stage_order_when_paid_at_precedes_placed_at():
    placed = datetime(2026, 9, 20, 18, tzinfo=UTC)
    events = [
        SimpleNamespace(
            event_type="ORDER_PLACED",
            occurred_at=placed,
            payload={"origin": "LEGACY_V1_BACKFILL"},
            dedupe_key="placed",
        ),
        SimpleNamespace(
            event_type="PAYMENT_CONFIRMED",
            occurred_at=placed - timedelta(hours=6),
            payload={"origin": "LEGACY_V1_BACKFILL"},
            dedupe_key="paid",
        ),
    ]
    assert _expected(events) == ("PAID", "NOT_SHIPPED", None)


def _seed_v1(connection, *, statuses=LEGACY_ORDER_STATUSES):
    merchant_id, product_id = uuid4(), uuid4()
    connection.execute(
        sa.text("""
        INSERT INTO merchants (id, merchant_code, display_name)
        VALUES (:id, :code, 'Borough test')
    """),
        {"id": merchant_id, "code": f"legacy-{merchant_id.hex}"},
    )
    connection.execute(
        sa.text("""
        INSERT INTO products
          (id, merchant_id, business_date, product_code, title, category, price, status, listed_at)
        VALUES (:id, :merchant_id, :day, 'old-p', '旧商品', '测试', 10, 'ONLINE', :at)
    """),
        {
            "id": product_id,
            "merchant_id": merchant_id,
            "day": date(2026, 9, 20),
            "at": datetime(2026, 9, 20, tzinfo=UTC),
        },
    )
    order_ids = {}
    placed_at = datetime(2026, 9, 20, 18, tzinfo=UTC)
    # 历史记录容许 paid_at 早于 placed_at；不能为事件排序改写原数据。
    paid_at = placed_at - timedelta(hours=6)
    for status in statuses:
        order_id = uuid4()
        order_ids[status] = order_id
        connection.execute(
            sa.text("""
            INSERT INTO orders
              (id, merchant_id, business_date, order_no, buyer_key, order_status,
               total_amount, paid_amount, placed_at, paid_at)
            VALUES (:id, :merchant_id, :day, :no, 'legacy-buyer', :status,
                    20, :paid_amount, :placed_at, :paid_at)
        """),
            {
                "id": order_id,
                "merchant_id": merchant_id,
                "day": date(2026, 9, 20),
                "no": f"legacy-{status}-{order_id.hex}",
                "status": status,
                "paid_amount": Decimal("20.00")
                if status in {"PAID", "SHIPPED", "COMPLETED"}
                else Decimal("0.00"),
                "placed_at": placed_at,
                "paid_at": paid_at if status in {"PAID", "SHIPPED", "COMPLETED"} else None,
            },
        )
        connection.execute(
            sa.text("""
            INSERT INTO order_items
              (id, merchant_id, business_date, order_id, product_id, quantity, item_amount)
            VALUES (:id, :merchant_id, :day, :order_id, :product_id, 2, 20)
        """),
            {
                "id": uuid4(),
                "merchant_id": merchant_id,
                "day": date(2026, 9, 20),
                "order_id": order_id,
                "product_id": product_id,
            },
        )
    return merchant_id, order_ids


def test_existing_v1_rows_backfill_and_downgrade_without_loss(postgres_url):
    config = alembic_config(postgres_url)
    engine = sa.create_engine(postgres_url)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, PRE_M2)
        with engine.begin() as connection:
            merchant_id, order_ids = _seed_v1(connection)
            before = (
                connection.execute(
                    sa.text("""
                SELECT order_no, order_status, total_amount, paid_amount, placed_at, paid_at
                FROM orders WHERE merchant_id = :merchant_id ORDER BY order_no
            """),
                    {"merchant_id": merchant_id},
                )
                .mappings()
                .all()
            )
        command.upgrade(config, M3)
        with engine.connect() as connection:
            for status, order_id in order_ids.items():
                row = connection.execute(
                    sa.text("""
                    SELECT payment_status, fulfillment_status, close_reason,
                           after_sale_status, lifecycle_origin
                    FROM orders WHERE id = :id
                """),
                    {"id": order_id},
                ).one()
                assert row[:3] == from_legacy_status(status)
                assert row[3:] == ("NONE", "LEGACY_V1")
                item = connection.execute(
                    sa.text("""
                    SELECT unit_price, discount_amount, line_total, item_amount
                    FROM order_items WHERE order_id = :id
                """),
                    {"id": order_id},
                ).one()
                assert item == (
                    Decimal("10.00"),
                    Decimal("0.00"),
                    Decimal("20.00"),
                    Decimal("20.00"),
                )
                events = (
                    connection.execute(
                        sa.text("""
                    SELECT event_type, payload, occurred_at FROM fulfillment_events
                    WHERE subject_id = :id ORDER BY event_type
                """),
                        {"id": order_id},
                    )
                    .mappings()
                    .all()
                )
                assert events
                assert all(e["payload"]["origin"] == "LEGACY_V1_BACKFILL" for e in events)
                assert {e["event_type"] for e in events} >= {"ORDER_PLACED"}
        command.downgrade(config, PRE_M2)
        with engine.connect() as connection:
            after = (
                connection.execute(
                    sa.text("""
                SELECT order_no, order_status, total_amount, paid_amount, placed_at, paid_at
                FROM orders WHERE merchant_id = :merchant_id ORDER BY order_no
            """),
                    {"merchant_id": merchant_id},
                )
                .mappings()
                .all()
            )
            assert [tuple(row.values()) for row in after] == [tuple(row.values()) for row in before]
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def test_ambiguous_legacy_paid_at_aborts_migration_atomically(postgres_url):
    config = alembic_config(postgres_url)
    engine = sa.create_engine(postgres_url)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, PRE_M2)
        with engine.begin() as connection:
            _, order_ids = _seed_v1(connection, statuses=("PAID",))
            connection.execute(
                sa.text("UPDATE orders SET paid_at = NULL WHERE id = :id"),
                {"id": order_ids["PAID"]},
            )
        with pytest.raises(DBAPIError, match="paid_at") as error:
            command.upgrade(config, "20260922_0018")
        assert_sqlstate(error, RAISE_EXCEPTION)
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == PRE_M2
            assert "payment_status" not in {
                c["name"] for c in sa.inspect(connection).get_columns("orders")
            }
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE orders SET paid_at = placed_at WHERE id = :id"),
                {"id": order_ids["PAID"]},
            )
    finally:
        command.upgrade(config, "head")
        engine.dispose()
