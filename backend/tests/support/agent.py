"""不联网的 ChatService 测试替身。

它只验证 ChatService 的持久化与幂等行为，不承担 B3 意图识别测试；后者由
``tests/unit/agent/test_graph.py`` 使用 FakeLlmClient 覆盖。
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.agent.graph import AgentRunResult
from app.schemas.chat import (
    AnalysisSource,
    AnswerMode,
    ChatResponse,
    MetricStatus,
    QualityStatus,
    QueryPlanSummary,
    Recommendation,
    ThinkingStep,
    Visualization,
)


class DeterministicAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, message: str, session_id: UUID) -> AgentRunResult:
        self.calls += 1
        response = ChatResponse(
            id=uuid4(),
            session_id=session_id,
            answer=f"测试问答图回答：{message}",
            answer_mode=AnswerMode.METRIC,
            category="TRADE",
            thinking_steps=[ThinkingStep(label="测试处理步骤", node="load_context")],
            quality_status=QualityStatus.DEGRADED,
            quality_attempts=0,
            quality_notes=["测试替身不执行真实经营数据查询。"],
            analysis_sources=[AnalysisSource.FALLBACK],
            degraded=True,
            degraded_reason="测试替身",
            query_plan=QueryPlanSummary(summary="测试查询计划"),
            metric_code="gmv",
            metric_display_name="成交 GMV",
            metric_unit="元",
            metric_definition="已支付订单金额之和。",
            metric_sql_definition="SUM(orders.paid_amount)",
            metric_dimensions=["date", "product", "category"],
            metric_source_database="public",
            metric_source_table="orders",
            metric_report_url=None,
            metric_source="METRIC_CATALOG",
            metric_generated=False,
            metric_notice=None,
            metric_owner="测试",
            metric_status=MetricStatus.ACTIVE,
            data_rows=[],
            total_rows=0,
            truncated=False,
            visualization=Visualization(enabled=False),
            recommendations=[
                Recommendation(title="测试建议一", evidence="测试证据", action="测试动作"),
                Recommendation(title="测试建议二", evidence="测试证据", action="测试动作"),
            ],
        )
        return AgentRunResult(response=response, steps=response.thinking_steps)
