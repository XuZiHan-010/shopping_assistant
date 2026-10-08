"""顾客端库存三档（PRD C1、D5）：只给档位，不给数量。

档位与商家端库存告警用同一条阈值线：商家看到「低库存」时，顾客看到的必须是「紧张」。
"""

from __future__ import annotations

import pytest

from app.schemas.v2.shop_session import StockBand
from app.services.v2.inventory_alerts import AlertRules
from app.services.v2.stock_tier import stock_band


@pytest.mark.parametrize(
    ("available", "threshold", "expected"),
    [
        (0, 5, StockBand.OUT_OF_STOCK),
        (-1, 5, StockBand.OUT_OF_STOCK),
        (1, 5, StockBand.LOW_STOCK),
        (5, 5, StockBand.LOW_STOCK),
        (6, 5, StockBand.IN_STOCK),
        (63, 5, StockBand.IN_STOCK),
        (1, 0, StockBand.IN_STOCK),
    ],
)
def test_band_follows_the_inventory_alert_threshold(
    available: int, threshold: int, expected: StockBand
) -> None:
    assert stock_band(available=available, low_stock_threshold=threshold) is expected


def test_missing_threshold_uses_the_shop_default() -> None:
    default = AlertRules().default_low_stock_threshold

    assert stock_band(available=default, low_stock_threshold=None) is StockBand.LOW_STOCK
    assert stock_band(available=default + 1, low_stock_threshold=None) is StockBand.IN_STOCK
