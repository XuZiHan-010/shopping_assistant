"""v2 图表可视化构造（N3 阶段 C，PRD M3，契约 §8.7.11）。

只测"从 `AttributionService` 的确定性输出构造 `Visualization`"这一层纯函数——
数据本身的正确性（等长可比周期、逐日相减、缺失日补零）已在 `test_attribution.py`
验证过，这里只测图表类型选择、标题、单位这几条 M3 既有规则的落地。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.schemas.chat import ChartType
from app.services.v2.attribution import (
    AttributionResult,
    DataSource,
    MetricSeriesPoint,
    MetricSeriesResult,
    Segment,
)
from app.services.v2.visualization import (
    build_visualization_for_attribution,
    build_visualization_for_series,
)


def _series(points: list[tuple[date, str]]) -> MetricSeriesResult:
    return MetricSeriesResult(
        points=tuple(MetricSeriesPoint(date=d, value=Decimal(v)) for d, v in points),
        data_cutoff=points[-1][0] if points else date(2026, 1, 1),
        source=DataSource.REALTIME,
        definition_version="v1",
    )


def test_series_defaults_to_line_chart_only() -> None:
    result = _series([(date(2026, 9, 20), "100"), (date(2026, 9, 21), "200")])

    viz = build_visualization_for_series(result, metric="gross_gmv")

    assert viz.enabled is True
    assert viz.type == ChartType.LINE
    assert viz.allowed_types == [ChartType.LINE]


def test_series_data_points_use_date_and_metric_keys() -> None:
    result = _series([(date(2026, 9, 20), "100")])

    viz = build_visualization_for_series(result, metric="gross_gmv")

    assert viz.dimension_key == "date"
    assert viz.metric_key == "gross_gmv"
    assert viz.data == [{"date": "2026-09-20", "gross_gmv": "100"}]


def test_series_title_and_unit_come_from_metric_spec() -> None:
    result = _series([(date(2026, 9, 20), "100")])

    viz = build_visualization_for_series(result, metric="gross_gmv")

    assert "趋势" in (viz.title or "")
    assert viz.unit == "元"


def test_net_gmv_series_uses_gross_gmv_display_metadata() -> None:
    """net_gmv 不在 METRIC_SPECS 里（它是查询层之上算出来的），标题/单位借用 gross_gmv 的。"""

    result = _series([(date(2026, 9, 20), "50")])

    viz = build_visualization_for_series(result, metric="net_gmv")

    assert viz.unit == "元"
    assert viz.metric_key == "net_gmv"


def test_empty_series_is_disabled_not_an_empty_chart() -> None:
    result = _series([])

    viz = build_visualization_for_series(result, metric="gross_gmv")

    assert viz.enabled is False


def test_attribution_defaults_to_bar_or_pie() -> None:
    result = AttributionResult(
        mode="SHARE",
        segments=(
            Segment(
                name="女装", current_value=Decimal("500"), baseline_value=Decimal("400"),
                share=Decimal("0.6"), absolute_contribution=Decimal("100"),
            ),
        ),
        comparison_label=("本周", "上周"),
        stopped=False,
        data_cutoff=date(2026, 9, 23),
        source=DataSource.REALTIME,
        definition_version="n3-metric-caliber-v1",
    )

    viz = build_visualization_for_attribution(result, metric="gross_gmv")

    assert viz.enabled is True
    assert viz.type == ChartType.BAR
    assert set(viz.allowed_types) == {ChartType.BAR, ChartType.PIE}
    assert viz.dimension_key == "category"
    assert viz.data == [{"category": "女装", "gross_gmv": "100"}]


def test_stopped_attribution_is_disabled() -> None:
    result = AttributionResult(
        mode="ABSOLUTE_CONTRIBUTION", segments=(), comparison_label=("本周", "上周"),
        stopped=True, stopped_reason="基期数据缺口",
        data_cutoff=date(2026, 9, 23), source=DataSource.REALTIME,
        definition_version="n3-metric-caliber-v1",
    )

    viz = build_visualization_for_attribution(result, metric="gross_gmv")

    assert viz.enabled is False
