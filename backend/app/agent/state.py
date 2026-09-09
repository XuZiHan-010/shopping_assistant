"""B3 问答图的显式状态定义。

节点只通过这个类型交换数据，避免把未经校验的匿名字典在节点间传递。
"""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from app.agent.prefilter import PrefilterDecision
from app.intent.models import QueryIntent
from app.intent.service import InitialIntent
from app.intent.whitelist import IntentValidation
from app.knowledge.retrieval import KnowledgeResult
from app.llm.client import LlmBudget
from app.localization.locales import SupportedLocale
from app.metrics.catalog import MetricPayload
from app.schemas.chat import (
    AnalysisSource,
    QualityStatus,
    Recommendation,
    ThinkingStep,
    Visualization,
)
from app.services.answer_service import AnswerFacts
from app.services.safe_query import QueryResult


class AgentState(TypedDict):
    request_id: str
    session_id: UUID
    question: str
    #: 本轮响应应渲染的显示语言，从 `Accept-Language` 解析而来（Task 2 的
    #: `get_request_locale`），由 `ChatService` 显式传入 `MerchantQaGraph.run()`。
    #: 节点只从这里读取，不读 Request 或任何无类型字典。
    locale: SupportedLocale
    #: 知识检索实际使用过的查询词序列，供跨语言召回排障与测试观测：至少包含
    #: 用户原问题；命中语料语言与目标语言不同时，追加一次规范化查询译文。
    retrieval_queries: list[str]
    knowledge_index: KnowledgeResult | None
    knowledge_detail: KnowledgeResult | None
    prefilter_decision: PrefilterDecision | None
    initial_intent: InitialIntent | None
    intent: QueryIntent | None
    intent_validation: IntentValidation | None
    metric_definition: MetricPayload | None
    query_result: QueryResult | None
    query_error: str | None
    answer_facts: AnswerFacts | None
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
