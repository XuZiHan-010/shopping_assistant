"""W 订单分页索引的升降级及 ORM 对齐。仅使用可丢弃测试库。"""

from alembic import command
from sqlalchemy import create_engine, inspect

from tests.postgres import alembic_config


def test_order_page_index_roundtrip(postgres_url: str) -> None:
    config = alembic_config(postgres_url)
    command.upgrade(config, "head")
    engine = create_engine(postgres_url)
    name = "ix_orders_v2_merchant_placed_id"
    try:
        indexes = {index["name"]: index for index in inspect(engine).get_indexes("orders")}
        assert name in indexes
        assert indexes[name]["column_names"] == ["merchant_id", "placed_at", "id"]
        assert "V2" in indexes[name]["dialect_options"]["postgresql_where"]
        command.check(config)
        command.downgrade(config, "20260928_0044")
        assert name not in {index["name"] for index in inspect(engine).get_indexes("orders")}
    finally:
        command.upgrade(config, "head")
        engine.dispose()
