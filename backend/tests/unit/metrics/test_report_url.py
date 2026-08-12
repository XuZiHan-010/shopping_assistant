"""指标报表链接与历史 JSONB 升级测试。"""

from app.metrics.report_url import normalize_report_url, upgrade_payload


def test_normalize_report_url_rejects_non_http_absolute_urls() -> None:
    for value in ("javascript:alert(1)", "data:text/html,x", "/internal/report"):
        assert normalize_report_url(value) is None

    assert normalize_report_url(" https://reports.example.com/gmv ") == (
        "https://reports.example.com/gmv"
    )


def test_upgrade_metric_payload_adds_only_safe_compatibility_defaults() -> None:
    historical = {
        "answer_mode": "METRIC",
        "metric_code": "gmv",
        "metric_source": "METRIC_CATALOG",
    }

    upgraded = upgrade_payload(historical)

    assert historical is not upgraded
    assert historical.keys() == {"answer_mode", "metric_code", "metric_source"}
    assert upgraded["metric_dimensions"] == []
    assert upgraded["metric_sql_definition"] == ""
    assert upgraded["metric_generated"] is False
    assert upgraded["metric_report_url"] is None
    assert upgrade_payload(upgraded) == upgraded
