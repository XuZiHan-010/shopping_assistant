"""顾客端库存三档（PRD C1、D5）：对外只有档位，永远不给数量。

阈值线与商家端库存告警**共用一处**（`AlertRules`）：商家收到「低库存」时，
顾客看到的必须同时是「紧张」，两边各设一条线迟早会互相矛盾。
"""

from __future__ import annotations

from app.schemas.v2.shop_session import StockBand
from app.services.v2.inventory_alerts import AlertRules

_DEFAULT_RULES = AlertRules()


def stock_band(
    *, available: int, low_stock_threshold: int | None, rules: AlertRules = _DEFAULT_RULES
) -> StockBand:
    threshold = (
        rules.default_low_stock_threshold if low_stock_threshold is None else low_stock_threshold
    )
    if available <= 0:
        return StockBand.OUT_OF_STOCK
    if available <= threshold:
        return StockBand.LOW_STOCK
    return StockBand.IN_STOCK
