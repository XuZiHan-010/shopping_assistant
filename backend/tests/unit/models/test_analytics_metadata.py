"""经营表的结构约束。

这些断言看着琐碎，但每一条都对应一个会泄漏或算错的场景：缺 merchant_id 就是
跨商家泄漏，缺 business_date 索引就是全表扫，金额用 float 就是对不上账。
"""

from __future__ import annotations

import pytest
from sqlalchemy import Numeric

from app.models.analytics import (
    Order,
    OrderItem,
    Product,
    Refund,
    ReturnRecord,
    SupportTicket,
)

ANALYTICS_MODELS = [Product, Order, OrderItem, Refund, ReturnRecord, SupportTicket]


@pytest.mark.parametrize("model", ANALYTICS_MODELS, ids=lambda m: m.__tablename__)
def test_every_analytics_table_carries_a_non_null_merchant_id(model: type) -> None:
    column = model.__table__.c["merchant_id"]

    assert column.nullable is False


@pytest.mark.parametrize("model", ANALYTICS_MODELS, ids=lambda m: m.__tablename__)
def test_every_analytics_table_carries_a_non_null_business_date(model: type) -> None:
    column = model.__table__.c["business_date"]

    assert column.nullable is False


@pytest.mark.parametrize("model", ANALYTICS_MODELS, ids=lambda m: m.__tablename__)
def test_every_analytics_table_indexes_merchant_and_business_date(model: type) -> None:
    expected = {"merchant_id", "business_date"}
    index_columns = [{column.name for column in index.columns} for index in model.__table__.indexes]

    assert any(expected <= columns for columns in index_columns), model.__tablename__


@pytest.mark.parametrize(
    ("model", "column_name"),
    [
        (Order, "paid_amount"),
        (Order, "total_amount"),
        (OrderItem, "item_amount"),
        (Product, "price"),
        (Refund, "refund_amount"),
    ],
)
def test_money_columns_use_numeric_not_float(model: type, column_name: str) -> None:
    assert isinstance(model.__table__.c[column_name].type, Numeric)


def test_refunds_and_returns_are_separate_tables_linked_to_order_items() -> None:
    """退款是资金动作、退货是货品动作，可以单独发生，合表会让两类指标互相污染。"""

    assert Refund.__tablename__ == "refunds"
    assert ReturnRecord.__tablename__ == "returns"
    for model in (Refund, ReturnRecord):
        foreign_keys = model.__table__.c["order_item_id"].foreign_keys
        assert {key.column.table.name for key in foreign_keys} == {"order_items"}


def test_returns_track_quantity_and_logistics_separately_from_refund_amount() -> None:
    """「最近 30 天退货量趋势」要能返回件数，不能退化成退款金额。"""

    assert "return_quantity" in ReturnRecord.__table__.c
    assert "logistics_status" in ReturnRecord.__table__.c
    assert "refund_amount" not in ReturnRecord.__table__.c
