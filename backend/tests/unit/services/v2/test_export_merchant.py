"""N3 阶段 C Task 5：商家明细导出（PRD M7）——`order_items` DetailSpec 补齐 + 工具层校验。

导出五类：订单、订单明细、退款、退货、工单。前一类由 v1 `DETAIL_SPECS["orders"]` 覆盖，
后三类同理已注册；本文件先确认"订单明细"（`order_items`）也在受控白名单内，
再测工具层不允许行数进对话、创建与下载各自审计的相关纯逻辑（不含真实 DB 的部分见集成测试）。
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.analytics.contract import DETAIL_SPECS
from app.tools.merchant.export import CreateExportArgs


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 9, 26), date(2026, 9, 25)),
        (date(2026, 1, 1), date(2026, 9, 26)),
    ],
)
def test_export_rejects_reversed_or_unbounded_date_range(start: date, end: date) -> None:
    with pytest.raises(ValidationError):
        CreateExportArgs(kind="orders", start=start, end=end)


def test_export_accepts_ninety_day_window() -> None:
    args = CreateExportArgs(kind="orders", start=date(2026, 6, 29), end=date(2026, 9, 26))
    assert (args.end - args.start).days == 89


def test_order_items_detail_is_registered_for_line_level_export() -> None:
    """PRD M7 五类导出之一"订单明细"，与"订单"（orders，整单）是两张不同的表。"""

    assert "order_items" in DETAIL_SPECS
    spec = DETAIL_SPECS["order_items"]
    assert spec.date_filtered is True


def test_five_export_kinds_all_registered() -> None:
    for table in ("orders", "order_items", "refunds", "returns", "support_tickets"):
        assert table in DETAIL_SPECS


def test_order_items_columns_exclude_buyer_identity() -> None:
    """R5：明细列白名单不含顾客手机号、地址等标识；顾客标识只能是脱敏别名（若涉及）。"""

    columns = {name for name, _ in DETAIL_SPECS["order_items"].columns}
    forbidden = {"buyer_key", "phone", "address", "buyer_phone", "shipping_address"}
    assert not (columns & forbidden)
