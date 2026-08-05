"""B3 问答图的显式状态定义。

节点只通过这个类型交换数据，避免把未经校验的匿名字典在节点间传递。
"""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from app.intent.models import QueryIntent
from app.intent.service import InitialIntent
from app.intent.whitelist import IntentValidation
from app.knowledge.retrieval import KnowledgeResult
from app.llm.client import LlmBudget
from app.metrics.catalog import MetricPayload
from app.schemas.chat import (
    AnalysisSource,
    QualityStatus,
    Recommendation,
    ThinkingStep,
    Visualization,
)
from app.services.safe_query import QueryResult


class AgentState(TypedDict):
    request_id: str
    session_id: UUID
    question: str
    knowledge_index: KnowledgeResult | None
    knowledge_detail: KnowledgeResult | None
    initial_intent: InitialIntent | None
    intent: QueryIntent | None
    intent_validation: IntentValidation | None
    metric_definition: MetricPayload | None
    query_result: QueryResult | None
    query_error: str | None
    candidate_answer: str
    visualization: Visualization | None
    recommendations: list[Recommendation]
    suggestions: list[str]
    suggestion_alternates: list[list[str]]
    analysis_sources: list[AnalysisSource]
    quality_status: QualityStatus
    quality_notes: list[str]
    attempt: int
    degraded: bool
    degraded_reason: str | None
    budget: LlmBudget
    steps: list[ThinkingStep]
