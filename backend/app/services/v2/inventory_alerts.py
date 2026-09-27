"""库存告警判定（PRD M5，契约 §8.12.1）。

判定全部是确定性规则，模型既不决定阈值也不决定是否告警。两条容易写错的规则：

- **销量为零时「可售天数」是 `null`**，不是无穷大、也不是一个很大的数——零销量说明
  我们不知道它能撑多久，伪精确值会让商家据此做补货决定；
- **新品不判滞销**：刚上架的商品没有销量是正常的，把它标成滞销会把新品保护期内的
  正常商品推给商家处理。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.schemas.v2.merchant_ops import InventoryAlert, InventoryAlertKind

SALES_WINDOW_DAYS: Final = 30
#: 告警严重度排序（§8.12.3）：售罄 → 低库存 → 滞销。
SEVERITY: Final = {
    InventoryAlertKind.OUT_OF_STOCK: 0,
    InventoryAlertKind.LOW_STOCK: 1,
    InventoryAlertKind.SLOW_MOVING: 2,
}


@dataclass(frozen=True)
class AlertRules:
    """全店口径的判定线；单个商品的阈值仍可覆盖 `default_low_stock_threshold`。"""

    default_low_stock_threshold: int = 5
    #: 近 30 天销量不超过这个数才可能算滞销。
    slow_moving_max_sales: int = 1
    #: 新品保护期：上架不足这么多天的商品不判滞销，与销量窗口对齐。
    new_product_protection_days: int = SALES_WINDOW_DAYS


@dataclass(frozen=True)
class InventoryFacts:
    """判定所需的全部事实，全部由后端确定性查询得出。"""

    product_id: str
    product_name: str
    stock_on_hand: int
    stock_reserved: int
    low_stock_threshold: int | None
    sold_last_30d: int
    listed_at: datetime

    @property
    def stock_available(self) -> int:
        return self.stock_on_hand - self.stock_reserved


def days_of_supply(available: int, sold_last_30d: int) -> int | None:
    """可售天数；销量为零时返回 `None`（未知 / 无近期销量）。"""

    if sold_last_30d <= 0:
        return None
    return available * SALES_WINDOW_DAYS // sold_last_30d


def evaluate_alert(
    facts: InventoryFacts, *, rules: AlertRules, now: datetime
) -> InventoryAlert | None:
    """返回该商品当前唯一的告警；没有问题时返回 `None`。"""

    kind = _kind(facts, rules=rules, now=now)
    if kind is None:
        return None
    threshold = _threshold(facts, rules=rules)
    return InventoryAlert(
        id=f"{kind.value}:{facts.product_id}",
        kind=kind,
        product_id=facts.product_id,
        product_name=facts.product_name,
        stock_on_hand=facts.stock_on_hand,
        stock_reserved=facts.stock_reserved,
        stock_available=facts.stock_available,
        low_stock_threshold=threshold,
        sold_last_30d=facts.sold_last_30d,
        days_of_supply=days_of_supply(facts.stock_available, facts.sold_last_30d),
    )


def _threshold(facts: InventoryFacts, *, rules: AlertRules) -> int:
    if facts.low_stock_threshold is None:
        return rules.default_low_stock_threshold
    return facts.low_stock_threshold


def _kind(facts: InventoryFacts, *, rules: AlertRules, now: datetime) -> InventoryAlertKind | None:
    available = facts.stock_available
    if available <= 0:
        return InventoryAlertKind.OUT_OF_STOCK
    if available <= _threshold(facts, rules=rules):
        return InventoryAlertKind.LOW_STOCK
    if _is_slow_moving(facts, rules=rules, now=now):
        return InventoryAlertKind.SLOW_MOVING
    return None


def _is_slow_moving(facts: InventoryFacts, *, rules: AlertRules, now: datetime) -> bool:
    if facts.sold_last_30d > rules.slow_moving_max_sales:
        return False
    protection_ends = facts.listed_at + timedelta(days=rules.new_product_protection_days)
    return now >= protection_ends


def sort_key(alert: InventoryAlert) -> tuple[int, str]:
    """§8.12.3 的稳定排序：严重度在前，同级按 `product_id` 升序，`id` 兜底。"""

    return SEVERITY[alert.kind], alert.product_id


def alerts_for(
    facts: Iterable[InventoryFacts],
    *,
    rules: AlertRules,
    now: datetime,
    kind: InventoryAlertKind | None = None,
) -> list[InventoryAlert]:
    alerts = [
        alert
        for alert in (evaluate_alert(item, rules=rules, now=now) for item in facts)
        if alert is not None and (kind is None or alert.kind == kind)
    ]
    return sorted(alerts, key=sort_key)
