"""`ToolResult.chart_data` 不进 LLM 看到的工具消息（N3 阶段 C，图表可视化，契约 §6.9 N3 落地补充）。

`chart_data` 与 `payload` 的分工：`payload` 是"给模型引用的汇总数字"，会被
`_tool_message()` 序列化进传给 LLM 的工具结果消息；`chart_data` 是"给图表用的完整
数据点"，只供 `LoopOutcome.tool_results` 的后端消费方读取，绝不出现在模型看到的内容里
——否则一个 180 点的时间序列会被模型逐字看到，既拉高 token 消耗，也让"模型不产生
图表数据点"这条 R4 底线名不副实（模型即使不生成也会看到，等同于握着方向盘）。
"""

from __future__ import annotations

import json

from app.agent.loop.runner import _tool_message
from app.schemas.v2.common import ToolDisplayStatus
from app.tools.types import ToolDisplay, ToolOutcome, ToolResult


def _display() -> ToolDisplay:
    return ToolDisplay(
        tool_name="query_metrics", call_id="c1", status=ToolDisplayStatus.SUCCEEDED,
        duration_ms=10, row_count=1,
    )


def test_chart_data_is_absent_from_the_tool_message() -> None:
    result = ToolResult(
        ok=True, payload={"metric": "gross_gmv", "value": "1000"}, display=_display(),
        reason_code=None, outcome=ToolOutcome.SUCCEEDED, summary="已完成",
        chart_data={"points": [{"date": "2026-09-20", "value": "100"}] * 180},
    )

    message = _tool_message(result)

    assert "points" not in message
    assert "2026-09-20" not in message


def test_payload_still_appears_in_the_tool_message() -> None:
    """只是 chart_data 被排除；payload 本身（模型需要引用的汇总数字）照常传给模型。"""

    result = ToolResult(
        ok=True, payload={"metric": "gross_gmv", "value": "1000"}, display=_display(),
        reason_code=None, outcome=ToolOutcome.SUCCEEDED, summary="已完成",
        chart_data={"points": []},
    )

    message = _tool_message(result)

    assert json.loads(message)["data"] == {"metric": "gross_gmv", "value": "1000"}


def test_chart_data_defaults_to_none_and_is_absent_for_other_tools() -> None:
    """绝大多数工具不填这个字段；默认值不应该在消息里凭空出现任何图表相关的键。"""

    result = ToolResult(
        ok=True, payload={"text": "普通结果"}, display=_display(), reason_code=None,
        outcome=ToolOutcome.SUCCEEDED, summary="已完成",
    )

    assert result.chart_data is None
    message = _tool_message(result)
    assert "chart" not in message.lower()
