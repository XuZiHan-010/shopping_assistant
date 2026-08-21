"""指标与维度的 SQL 契约。

这张注册表是「用户输入永远不进入 SQL 标识符位置」的兑现方式：查询层只接受
这里的键，别的一律拒绝。它与 B3 白名单漂移，就等于开了一个静默失效的口子。
"""

from __future__ import annotations

import pytest

from app.analytics.contract import (
    DETAIL_SPECS,
    DIMENSION_SPECS,
    METRIC_SPECS,
    DetailSpec,
    DimensionSpec,
    UnknownFieldError,
    compatible_dimensions,
    dimension_spec,
    metric_spec,
)
from app.intent.whitelist import DIMENSION_WHITELIST, METRIC_WHITELIST


def test_metric_registry_matches_the_intent_whitelist() -> None:
    assert set(METRIC_SPECS) == set(METRIC_WHITELIST)


def test_dimension_registry_matches_the_intent_whitelist() -> None:
    assert set(DIMENSION_SPECS) == set(DIMENSION_WHITELIST)


def test_registry_matches_the_metric_seed() -> None:
    from app.metrics.seed import METRIC_SEED

    seed = {item.metric_code: item for item in METRIC_SEED}
    for code, spec in METRIC_SPECS.items():
        assert seed[code].display_name == spec.label, code
        assert seed[code].unit == spec.unit, code


@pytest.mark.parametrize("code", ["ordering_user_count", "paying_user_count", "return_rate"])
def test_non_additive_metrics_are_marked(code: str) -> None:
    """去重计数和比例跨区间相加就是错的；标记丢失时 B5 会把它们求和。"""

    assert METRIC_SPECS[code].additive is False


@pytest.mark.parametrize("code", ["gmv", "order_count", "refund_amount", "return_count"])
def test_additive_metrics_are_marked(code: str) -> None:
    assert METRIC_SPECS[code].additive is True


def test_refund_and_return_metrics_read_different_tables() -> None:
    """退款是资金动作、退货是货品动作，读错表就会「退货量趋势」返回退款数据。"""

    assert METRIC_SPECS["refund_count"].table == "refunds"
    assert METRIC_SPECS["refund_amount"].table == "refunds"
    assert METRIC_SPECS["return_count"].table == "returns"


def test_unknown_metric_raises_instead_of_returning_none() -> None:
    """静默返回 None 会让调用方在下一步才炸，错误信息离现场很远。"""

    with pytest.raises(UnknownFieldError):
        metric_spec("gmv; DROP TABLE orders")


def test_unknown_dimension_raises() -> None:
    with pytest.raises(UnknownFieldError):
        dimension_spec("seller_secret")


def test_refund_reason_is_not_offered_for_gmv() -> None:
    """按退款原因拆 GMV 没有业务含义，也没有可用的连接路径。"""

    assert "refund_reason" not in compatible_dimensions(METRIC_SPECS["gmv"])
    assert "refund_reason" in compatible_dimensions(METRIC_SPECS["refund_amount"])


def test_date_is_compatible_with_every_metric() -> None:
    for spec in METRIC_SPECS.values():
        assert "date" in compatible_dimensions(spec), spec.code


def test_products_detail_is_not_filtered_by_business_date() -> None:
    """`products.business_date` 是上架日，不是业务事件日。

    事件表（订单/退款/退货/工单）套用「查询区间内的 business_date」是对的；
    维度表套用同一条规则会让商家问「看看我的商品明细」时，只拿到默认 7 天
    窗口里恰好上架的那一两个商品，其余全部被静默过滤掉。
    """

    assert DETAIL_SPECS["products"].date_filtered is False


@pytest.mark.parametrize(
    "table", ["orders", "refunds", "returns", "support_tickets"], ids=lambda t: str(t)
)
def test_event_detail_tables_stay_filtered_by_business_date(table: str) -> None:
    """放宽只针对维度表；事件表丢掉时间窗等于每次都全表返回。"""

    assert DETAIL_SPECS[table].date_filtered is True


def test_date_filtering_defaults_to_on_for_new_detail_specs() -> None:
    """新增明细表时忘了想时间语义，应该退到「按业务日过滤」这条更保守的默认。"""

    assert DetailSpec("x", "x", (("business_date", "日期"),)).date_filtered is True


@pytest.mark.parametrize("spec", list(DIMENSION_SPECS.values()), ids=lambda s: str(s.code))
def test_every_dimension_column_exists_on_its_model(spec: DimensionSpec) -> None:
    """维度列和明细列是同一类接缝：`_dimension_column` 也用 `getattr` 解析。

    写错列名同样是**请求期**的 AttributeError，只有真的按那个维度拆分过才会暴露。
    """

    from app.repositories.analytics import _TABLES

    if not spec.table:
        # 空 table 是「用主表自己的列」的约定，目前只有 date：它落到本次查询主表的
        # business_date 上，主表是哪张由指标决定，所以六张经营表都必须有这一列。
        assert spec.column == "business_date", "空 table 的约定只覆盖业务日列"
        for table, model in _TABLES.items():
            assert spec.column in model.__table__.c, f"{table}.{spec.column}"
        return

    assert spec.column in _TABLES[spec.table].__table__.c, f"{spec.table}.{spec.column}"


@pytest.mark.parametrize("spec", list(DIMENSION_SPECS.values()), ids=lambda s: str(s.code))
def test_every_dimension_table_is_a_known_analytics_table(spec: DimensionSpec) -> None:
    """`table` 写成注册表里没有的名字，会在 `_TABLES[...]` 处抛 KeyError，同样是请求期。"""

    from app.repositories.analytics import _TABLES

    assert spec.table == "" or spec.table in _TABLES, spec.code


@pytest.mark.parametrize("spec", list(DETAIL_SPECS.values()), ids=lambda s: str(s.table))
def test_every_detail_column_exists_on_its_model(spec: DetailSpec) -> None:
    """`AnalyticsRepository.detail()` 用 `getattr(table, name)` 解析列。

    列名写错不是导入期错误，是**请求期**的 AttributeError——只有真的查过那张
    表才会暴露。契约里登记了五张明细表，此前只有三张被任何测试触达过；这条把
    「契约列名 ↔ ORM 列」这道接缝整体钉住，不依赖某张表恰好有人查。
    """

    from app.repositories.analytics import _TABLES

    columns = _TABLES[spec.table].__table__.c
    for name, label in spec.columns:
        assert name in columns, f"{spec.table}.{name}"
        assert label, f"{spec.table}.{name} 缺中文标签"
