"""Task 4：报告生成与脱敏。

只有确定性安全集是门禁；随机攻击集与质量指标只报告数值/置信区间，不参与
`gate_passed` 判定（E3）。报告不含隐私与密钥：渲染时过滤已知密钥环境变量的
当前取值，并对手机号形态字符串、`buyer_key`/会话凭证等字段名做整体掩码。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
#: 生成时从环境变量读取当前取值并整体替换——不依赖调用方记得脱敏。
_SECRET_ENV_VARS: tuple[str, ...] = (
    "LLM_API_KEY",
    "ADMIN_TOKEN",
    "VIEWER_TOKEN",
    "BUYER_ALIAS_SECRET",
)
#: 字段名本身（不只是值）也不得出现在报告里——`buyer_key` 即使脱敏了值，
#: 字段名留在报告里仍会告诉攻击者「这里有顾客身份」。
_SENSITIVE_FIELD_NAMES: tuple[str, ...] = (
    "buyer_key",
    "session_id",
    "x-session-id",
    "authorization",
    "x-admin-token",
    "cookie",
    "set-cookie",
    "api_key",
    "llm_api_key",
    "admin_token",
    "viewer_token",
    "buyer_alias_secret",
    "access_token",
    "refresh_token",
    "password",
)
_FIELD_NAME_PATTERN = re.compile(
    "|".join(re.escape(name) for name in _SENSITIVE_FIELD_NAMES), re.IGNORECASE
)


@dataclass(frozen=True)
class CaseReportEntry:
    case_id: str
    passed: bool
    failure_detail: str = ""
    #: 供失败排查用的原始请求/响应片段；渲染前必须先经过 `_redact()`。
    raw_payload: str = ""


@dataclass(frozen=True)
class QualityMetrics:
    """E3 要求的质量指标；未计算的维度留 `None`，报告里直接省略该行。"""

    task_completion_rate: float | None = None
    tool_call_accuracy: float | None = None
    number_traceability_rate: float | None = None
    side_effect_correctness: float | None = None
    idempotency_rate: float | None = None
    citation_fidelity: float | None = None
    p95_latency_ms: float | None = None
    cost_cny: float | None = None


@dataclass(frozen=True)
class DatasetReport:
    security_results: Sequence[CaseReportEntry]
    random_attack_results: Sequence[CaseReportEntry] = ()
    quality_metrics: QualityMetrics = field(default_factory=QualityMetrics)


@dataclass(frozen=True)
class RenderedReport:
    text: str
    #: 只由 `security_results` 决定，`random_attack_results` 与质量指标不参与。
    gate_passed: bool


def _redact(text: str) -> str:
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError):
        payload = None
    if isinstance(payload, (dict, list)):
        try:
            text = json.dumps(_redact_json(payload), ensure_ascii=False)
        except RecursionError:
            return "[REDACTED-FIELD]"
    elif _FIELD_NAME_PATTERN.search(text):
        # 非结构化/截断片段无法确定值的边界；整段遮蔽，不能只抹字段名。
        return "[REDACTED-FIELD]"
    return _redact_secrets(text)


def _redact_json(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _redact_json(item)
            for key, item in value.items()
            if not _FIELD_NAME_PATTERN.search(key)
        }
    if isinstance(value, list):
        # 请求头也可能以 [name, value] 数组对序列化；必须连同值一起移除。
        if len(value) == 2 and isinstance(value[0], str) and _FIELD_NAME_PATTERN.search(value[0]):
            return "[REDACTED-FIELD]"
        return [_redact_json(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _redact_secrets(text: str) -> str:
    redacted = text
    for env_name in _SECRET_ENV_VARS:
        value = os.environ.get(env_name)
        if value:
            redacted = redacted.replace(value, "[REDACTED]")
    redacted = _PHONE_PATTERN.sub("[REDACTED-PHONE]", redacted)
    return redacted


def _confidence_interval(entries: Sequence[CaseReportEntry]) -> str:
    if not entries:
        return "无样本"
    total = len(entries)
    passed = sum(1 for entry in entries if entry.passed)
    rate = passed / total
    margin = 1.96 * ((rate * (1 - rate)) / total) ** 0.5
    low = max(0.0, rate - margin)
    high = min(1.0, rate + margin)
    return f"{rate:.1%}（95% 置信区间 {low:.1%}–{high:.1%}，n={total}）"


_METRIC_LABELS: tuple[tuple[str, str, str], ...] = (
    ("task_completion_rate", "任务完成率", "{:.1%}"),
    ("tool_call_accuracy", "工具调用正确率", "{:.1%}"),
    ("number_traceability_rate", "数字可追溯率", "{:.1%}"),
    ("side_effect_correctness", "副作用正确性", "{:.1%}"),
    ("idempotency_rate", "幂等性", "{:.1%}"),
    ("citation_fidelity", "引用忠实度", "{:.1%}"),
    ("p95_latency_ms", "p95 延迟", "{:.0f} ms"),
    ("cost_cny", "成本", "¥{:.2f}"),
)


def render_report(
    report: DatasetReport, *, gate_title: str = "安全硬门禁（零失败，门禁判据）"
) -> RenderedReport:
    """`gate_title` 只影响标题文案：调用方用同一个字段名 `security_results` 渲染
    非安全集（例如 Task 7 的质量基线）时，换一个准确的标题，不要沿用「安全硬门禁」
    误导读者以为这是权限判定。`gate_passed` 语义不变——恒等于 `security_results`
    是否非空且全部通过。
    """

    gate_passed = bool(report.security_results) and all(
        entry.passed for entry in report.security_results
    )

    lines = ["# 评测报告", "", f"## {_redact(gate_title)}"]
    if not report.security_results:
        lines.append("- 无安全评测样本，不能判定通过")
    for entry in report.security_results:
        lines.append(f"- {_redact(entry.case_id)}：{'通过' if entry.passed else '失败'}")
        if not entry.passed and entry.failure_detail:
            lines.append(f"  - {_redact(entry.failure_detail)}")
    lines.append(f"- 门禁结论：{'通过' if gate_passed else '不通过'}")

    if report.random_attack_results:
        lines += ["", "## 随机攻击集（仅报告置信区间，不参与门禁）"]
        lines.append(f"- 通过率：{_confidence_interval(report.random_attack_results)}")

    metric_lines = [
        (label, getattr(report.quality_metrics, attr), fmt)
        for attr, label, fmt in _METRIC_LABELS
        if getattr(report.quality_metrics, attr) is not None
    ]
    if metric_lines:
        lines += ["", "## 质量指标"]
        for label, value, fmt in metric_lines:
            lines.append(f"- {label}：{fmt.format(value)}")

    for entry in (*report.security_results, *report.random_attack_results):
        if entry.raw_payload:
            lines += [
                "",
                f"### {_redact(entry.case_id)} 原始载荷（已脱敏）",
                "```",
                _redact(entry.raw_payload),
                "```",
            ]

    return RenderedReport(text=_redact_secrets("\n".join(lines)), gate_passed=gate_passed)
