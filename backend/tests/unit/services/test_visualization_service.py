from __future__ import annotations

from decimal import Decimal

from app.metrics.catalog import MetricPayload
from app.repositories.analytics import ResultColumn
from app.services.safe_query import QueryResult


def _metric() -> MetricPayload:
    return MetricPayload(
        metric_code="gmv",
        display_name="成交 GMV",
        unit="元",
        definition="已付款订单金额之和",
        source="Borough 指标目录",
        owner="经营分析组",
        status="ACTIVE",
        generated=False,
        notice=None,
    )


def _result(*, columns: tuple[ResultColumn, ...], rows: list[dict[str, object]]) -> QueryResult:
    return QueryResult(
        columns=columns,
        rows=rows,
        total_rows=len(rows),
        truncated=False,
        source_tables=("orders",),
        plan_steps=("按日期汇总成交 GMV",),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


def test_date_dimension_builds_line_chart_from_query_rows() -> None:
    from app.services.visualization_service import VisualizationService

    result = _result(
        columns=(
            ResultColumn("date", "日期", "DIMENSION"),
            ResultColumn("gmv", "成交 GMV", "METRIC"),
        ),
        rows=[{"date": "2026-08-01", "gmv": Decimal("12.00")}],
    )

    chart = VisualizationService().build(result, _metric())

    assert chart.enabled is True
    assert chart.type.value == "LINE"
    assert chart.dimension_key == "date"
    assert chart.metric_key == "gmv"
    assert chart.unit == "元"
    assert chart.data == [{"date": "2026-08-01", "gmv": "12.00"}]


def test_unknown_or_missing_metric_column_disables_chart() -> None:
    from app.services.visualization_service import VisualizationService

    result = _result(
        columns=(ResultColumn("product_name", "商品名称", "DIMENSION"),),
        rows=[{"product_name": "Borough 帆布包"}],
    )

    chart = VisualizationService().build(result, _metric())

    assert chart.enabled is False
    assert chart.data == []


def test_generated_trade_metric_uses_the_fixed_paid_amount_column() -> None:
    from app.services.visualization_service import VisualizationService

    generated = MetricPayload(
        metric_code="generated_trade_metric",
        display_name="按 SPU 看成交表现",
        unit="元",
        definition="由交易固定聚合模板计算。",
        source="AI_GENERATED",
        owner="待认领",
        status="UNVERIFIED",
        generated=True,
        notice="展示名称待人工核验。",
    )
    result = _result(
        columns=(
            ResultColumn("spu_id", "SPU ID", "DIMENSION"),
            ResultColumn("paid_amount", "成交金额", "METRIC"),
        ),
        rows=[{"spu_id": "SPU-1", "paid_amount": Decimal("12.00")}],
    )

    chart = VisualizationService().build(result, generated)

    assert chart.enabled is True
    assert chart.type.value == "BAR"
    assert chart.dimension_key == "spu_id"
    assert chart.metric_key == "paid_amount"
    assert chart.data == [{"spu_id": "SPU-1", "paid_amount": "12.00"}]


def _generated(*, display_name: str, unit: str) -> MetricPayload:
    return MetricPayload(
        metric_code="generated_trade_metric",
        display_name=display_name,
        unit=unit,
        definition="由固定聚合模板计算。",
        source="AI_GENERATED",
        owner="待认领",
        status="UNVERIFIED",
        generated=True,
        notice="展示名称待人工核验。",
    )


def _trade_columns() -> tuple[ResultColumn, ...]:
    return (
        ResultColumn("address_city_name", "收货城市", "DIMENSION"),
        ResultColumn("order_count", "成交订单数", "METRIC"),
        ResultColumn("order_user_count", "成交用户数", "METRIC"),
        ResultColumn("quantity", "成交件数", "METRIC"),
        ResultColumn("paid_amount", "成交金额", "METRIC"),
    )


def _trade_row() -> dict[str, object]:
    return {
        "address_city_name": "上海",
        "order_count": 12,
        "order_user_count": 9,
        "quantity": 20,
        "paid_amount": Decimal("880.00"),
    }


def test_generated_metric_plots_the_count_column_when_the_plan_declares_orders() -> None:
    """计划声明的是订单数，图表就不能画成交金额——标题和数值必须是同一件事。"""

    from app.services.visualization_service import VisualizationService

    chart = VisualizationService().build(
        _result(columns=_trade_columns(), rows=[_trade_row()]),
        _generated(display_name="各城市成交订单数", unit="单"),
    )

    assert chart.metric_key == "order_count"
    assert chart.data == [{"address_city_name": "上海", "order_count": 12}]


def test_generated_metric_plots_the_user_column_when_the_plan_declares_people() -> None:
    from app.services.visualization_service import VisualizationService

    chart = VisualizationService().build(
        _result(columns=_trade_columns(), rows=[_trade_row()]),
        _generated(display_name="各城市下单用户数", unit="人"),
    )

    assert chart.metric_key == "order_user_count"


def test_generated_metric_plots_the_quantity_column_when_the_plan_declares_pieces() -> None:
    from app.services.visualization_service import VisualizationService

    chart = VisualizationService().build(
        _result(columns=_trade_columns(), rows=[_trade_row()]),
        _generated(display_name="各城市销量", unit="件"),
    )

    assert chart.metric_key == "quantity"


def test_generated_refund_metric_plots_the_refund_count_column() -> None:
    from app.services.visualization_service import VisualizationService

    columns = (
        ResultColumn("address_city_name", "收货城市", "DIMENSION"),
        ResultColumn("refund_count", "退款笔数", "METRIC"),
        ResultColumn("refund_user_count", "退款用户数", "METRIC"),
        ResultColumn("refund_amount", "退款金额", "METRIC"),
    )
    rows = [
        {
            "address_city_name": "上海",
            "refund_count": 3,
            "refund_user_count": 2,
            "refund_amount": Decimal("66.00"),
        }
    ]

    chart = VisualizationService().build(
        _result(columns=columns, rows=rows),
        _generated(display_name="各城市退款笔数", unit="笔"),
    )

    assert chart.metric_key == "refund_count"
