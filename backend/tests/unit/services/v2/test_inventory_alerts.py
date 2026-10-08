"""库存告警的确定性判定规则（M5，契约 §8.12.1）。

判定不碰数据库也不碰模型：给定一组库存事实，输出必须完全可预测。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.v2.merchant_ops import InventoryAlertKind
from app.services.v2.inventory_alerts import AlertRules, InventoryFacts, evaluate_alert

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=UTC)
RULES = AlertRules(default_low_stock_threshold=5)


def _facts(
    *,
    on_hand: int = 40,
    reserved: int = 0,
    threshold: int | None = 5,
    sold_last_30d: int = 30,
    listed_days_ago: int = 400,
) -> InventoryFacts:
    return InventoryFacts(
        product_id="p-1",
        product_name="测试商品",
        stock_on_hand=on_hand,
        stock_reserved=reserved,
        low_stock_threshold=threshold,
        sold_last_30d=sold_last_30d,
        listed_at=NOW - timedelta(days=listed_days_ago),
    )


def test_zero_sales_yields_unknown_days_not_infinity() -> None:
    """销量为零时可售天数是「未知」，不产生伪精确值（M5）。"""

    alert = evaluate_alert(_facts(on_hand=40, sold_last_30d=0), rules=RULES, now=NOW)

    assert alert is not None
    assert alert.days_of_supply is None


def test_new_product_is_not_flagged_slow_moving() -> None:
    """新品不直接判滞销：零销量可能只是刚上架。"""

    alert = evaluate_alert(
        _facts(on_hand=40, sold_last_30d=0, listed_days_ago=5), rules=RULES, now=NOW
    )

    assert alert is None


def test_threshold_falls_back_to_shop_default() -> None:
    """商品没有单独阈值时取全店默认值。"""

    alert = evaluate_alert(_facts(on_hand=4, threshold=None), rules=RULES, now=NOW)

    assert alert is not None
    assert alert.kind == InventoryAlertKind.LOW_STOCK
    assert alert.low_stock_threshold == RULES.default_low_stock_threshold


def test_product_threshold_overrides_shop_default() -> None:
    alert = evaluate_alert(_facts(on_hand=8, threshold=10), rules=RULES, now=NOW)

    assert alert is not None
    assert alert.kind == InventoryAlertKind.LOW_STOCK
    assert alert.low_stock_threshold == 10


def test_out_of_stock_is_decided_by_available_not_on_hand() -> None:
    """可售 = 在库 − 占用：在库还有货但全被占用，仍然是售罄。"""

    alert = evaluate_alert(_facts(on_hand=12, reserved=12), rules=RULES, now=NOW)

    assert alert is not None
    assert alert.kind == InventoryAlertKind.OUT_OF_STOCK
    assert alert.stock_on_hand == 12
    assert alert.stock_available == 0


def test_out_of_stock_takes_precedence_over_low_stock() -> None:
    alert = evaluate_alert(_facts(on_hand=0, threshold=5, sold_last_30d=0), rules=RULES, now=NOW)

    assert alert is not None
    assert alert.kind == InventoryAlertKind.OUT_OF_STOCK


def test_healthy_product_has_no_alert() -> None:
    assert evaluate_alert(_facts(on_hand=400, sold_last_30d=30), rules=RULES, now=NOW) is None


def test_slow_moving_requires_remaining_stock_and_aged_listing() -> None:
    alert = evaluate_alert(
        _facts(on_hand=40, sold_last_30d=1, listed_days_ago=400), rules=RULES, now=NOW
    )

    assert alert is not None
    assert alert.kind == InventoryAlertKind.SLOW_MOVING
    assert alert.days_of_supply == 40 * 30


@pytest.mark.parametrize(
    ("available", "sold", "expected"),
    [(60, 30, 60), (45, 30, 45), (14, 30, 14), (45, 60, 22), (1, 30, 1)],
)
def test_days_of_supply_uses_thirty_day_rate(available: int, sold: int, expected: int) -> None:
    """可售天数 = 可售量 ÷ 日均销量，向下取整（不高估还能撑几天）。"""

    # 阈值取足够大，保证每种取值都会产生一条低库存告警，断言只比可售天数。
    facts = _facts(on_hand=available, threshold=10_000, sold_last_30d=sold)

    alert = evaluate_alert(facts, rules=RULES, now=NOW)

    assert alert is not None
    assert alert.days_of_supply == expected


def test_low_stock_alert_reports_the_whole_stock_triple() -> None:
    """商家可见精确三元组；顾客端只有档位（§8.12）。"""

    alert = evaluate_alert(_facts(on_hand=6, reserved=2, threshold=5), rules=RULES, now=NOW)

    assert alert is not None
    assert (alert.stock_on_hand, alert.stock_reserved, alert.stock_available) == (6, 2, 4)
    assert alert.kind == InventoryAlertKind.LOW_STOCK
