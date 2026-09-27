"""Task 4：报告生成与脱敏。"""

from __future__ import annotations

import json
import re

import pytest

from app.eval.report import CaseReportEntry, DatasetReport, QualityMetrics, render_report


def _report_with_raw_payloads() -> DatasetReport:
    return DatasetReport(
        security_results=[
            CaseReportEntry(
                case_id="SEC-CROSS-001",
                passed=False,
                failure_detail="[http_status] 期望状态码 403，实得 200",
                raw_payload=(
                    "Authorization: Bearer sk-real-key-value\n"
                    "buyer_key: 13800001234-secret\n"
                    "顾客手机号：13912345678"
                ),
            ),
            CaseReportEntry(case_id="SEC-CROSS-002", passed=True),
        ]
    )


def test_report_never_contains_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-real-key-value")

    rendered = render_report(_report_with_raw_payloads())

    assert "sk-real-key-value" not in rendered.text
    assert not re.search(r"1[3-9]\d{9}", rendered.text)
    assert "buyer_key" not in rendered.text.lower()


def test_gate_fails_when_any_security_case_fails() -> None:
    rendered = render_report(_report_with_raw_payloads())
    assert rendered.gate_passed is False


def test_gate_passes_when_all_security_cases_pass() -> None:
    report = DatasetReport(
        security_results=[
            CaseReportEntry(case_id="SEC-CROSS-001", passed=True),
            CaseReportEntry(case_id="SEC-CROSS-002", passed=True),
        ]
    )
    assert render_report(report).gate_passed is True


def test_random_set_is_reported_but_not_gating() -> None:
    """随机攻击集全部失败也不得影响门禁结论——只有安全集门禁（E3）。"""

    report = DatasetReport(
        security_results=[CaseReportEntry(case_id="SEC-CROSS-001", passed=True)],
        random_attack_results=[
            CaseReportEntry(case_id="RAND-001", passed=False),
            CaseReportEntry(case_id="RAND-002", passed=False),
        ],
    )

    rendered = render_report(report)

    assert "置信区间" in rendered.text
    assert rendered.gate_passed is True


def test_quality_metrics_render_only_when_present() -> None:
    report = DatasetReport(
        security_results=[CaseReportEntry(case_id="SEC-CROSS-001", passed=True)],
        quality_metrics=QualityMetrics(task_completion_rate=0.92, p95_latency_ms=850),
    )

    text = render_report(report).text

    assert "任务完成率：92.0%" in text
    assert "p95 延迟：850 ms" in text
    assert "工具调用正确率" not in text


@pytest.mark.parametrize("location", ["raw_payload", "failure_detail", "case_id"])
@pytest.mark.parametrize(
    "payload",
    [
        '{"session_id":"mock-private-session","buyer_key":"mock-private-buyer"}',
        json.dumps(
            {
                "response": [{"buyer_key": {"value": "mock-private-buyer"}}],
                "headers": {
                    "Authorization": "Bearer mock-private-token",
                    "X-Admin-Token": "mock-private-admin",
                    "X-Session-Id": "mock-private-session",
                },
            }
        ),
        "Authorization: Bearer mock-private-token\nX-Session-Id: mock-private-session",
        '{"headers": [["authorization", "Bearer mock-private-token"]]}',
        'response={"buyer_key": "mock-private-buyer with spaces"}',
        '{"buyer_key": "mock-private-buyer\\" suffix"}',
    ],
)
def test_sensitive_values_are_removed_from_all_report_fields(location: str, payload: str) -> None:
    fields = {"case_id": "SEC-001", "failure_detail": "", "raw_payload": ""}
    fields[location] = payload
    rendered = render_report(
        DatasetReport(
            security_results=[
                CaseReportEntry(
                    passed=False,
                    **fields,
                )
            ]
        )
    )
    assert "mock-private" not in rendered.text
    assert "buyer_key" not in rendered.text.lower()
    assert "门禁结论：不通过" in rendered.text


def test_json_redaction_preserves_public_diagnostics() -> None:
    rendered = render_report(
        DatasetReport(
            security_results=[
                CaseReportEntry(
                    case_id="SEC-001",
                    passed=False,
                    raw_payload='{"status":403,"data":{"session_id":"mock-private-session"}}',
                )
            ]
        )
    )
    assert '"status": 403' in rendered.text
    assert "mock-private-session" not in rendered.text


def test_empty_security_results_cannot_pass_gate() -> None:
    assert render_report(DatasetReport(security_results=[])).gate_passed is False
