"""指标与维度的 SQL 契约。

这张注册表是「用户输入永远不进入 SQL 标识符位置」的兑现方式：查询层只接受
这里的键，别的一律拒绝。它与 B3 白名单漂移，就等于开了一个静默失效的口子。
"""

from __future__ import annotations

import pytest

from app.analytics.contract import (
    DIMENSION_SPECS,
    METRIC_SPECS,
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


@pytest.mark.parametrize("code", ["paying_user_count", "return_rate"])
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
