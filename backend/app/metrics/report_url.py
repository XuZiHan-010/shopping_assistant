"""指标关联报表链接的安全规范化。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.schemas.chat import AnswerMode


def normalize_report_url(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def upgrade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """为旧 METRIC JSONB 回放补默认值，且不修改数据库返回的原字典。"""

    upgraded = dict(payload)
    if upgraded.get("answer_mode") != AnswerMode.METRIC.value:
        return upgraded
    defaults: dict[str, Any] = {
        "metric_sql_definition": "",
        "metric_dimensions": [],
        "metric_source_database": "",
        "metric_source_table": "",
        "metric_report_url": None,
        "metric_generated": False,
        "metric_notice": None,
    }
    for key, value in defaults.items():
        upgraded.setdefault(key, value)
    return upgraded
