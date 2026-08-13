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
