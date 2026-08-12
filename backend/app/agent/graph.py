"""商家问答 LangGraph。

图的节点顺序与后端设计 §10 一致。`query_data` 在注入了查询服务时执行真实的
受控经营查询；质量复核相关节点仍是可见的 passthrough，保证 SSE 处理轨迹与
后续阶段兼容，而不伪装成已完成的数据分析。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from time import monotonic
from typing import Any, Final, Protocol, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState
from app.core.security import MerchantContext
from app.intent.models import QueryIntent
from app.intent.service import IntentService
from app.knowledge.retrieval import KnowledgeResult, KnowledgeRetrieval
from app.llm.client import LlmBudget, LlmClient
from app.metrics.catalog import MetricCatalog, MetricPayload
from app.schemas.answer import AnswerDraft
from app.schemas.chat import (
    AnalysisSource,
    AnswerMode,
    ChatResponse,
    ExportInfo,
    MetricStatus,
    QualityStatus,
    QueryPlanSummary,
    Recommendation,
    ThinkingStep,
    Visualization,
)
from app.services.answer_service import AnswerFacts, AnswerService
from app.services.review_service import ReviewService
from app.services.safe_query import QueryResult, UnsupportedQueryError
from app.services.suggested_questions import suggestions_for
from app.services.visualization_service import VisualizationService


class QueryServiceLike(Protocol):
    """`_query_data` 需要的最小接口；真实实现是 B4 的 `SafeQueryService`。"""

    async def execute(
        self,
        context: MerchantContext,
        intent: QueryIntent,
        *,
        now: datetime,
        keywords: Sequence[str] = (),
    ) -> QueryResult: ...


class NodeTimerLike(Protocol):
    """记录 Agent 节点耗时的最小接口。"""

    def record_node_duration(self, node: str, duration_seconds: float) -> None: ...


MAX_REVIEW_ATTEMPTS: Final[int] = 2

#: 只在「查询服务根本没注入」时用（查询被拒时 `degraded_reason` 取
#: `UnsupportedQueryError.reason`，那条更具体）。不写「将在某阶段接入」——受控查询
#: 本身已经交付，这么说会让用户以为功能还没上线，而实际是这次请求没能查成。
_QUERY_SERVICE_UNAVAILABLE: Final[str] = "经营数据查询服务当前不可用，本次未执行查询"
GRAPH_NODES: Final[tuple[str, ...]] = (
    "load_context",
    "retrieve_knowledge_index",
    "classify_intent",
    "understand_intent",
    "validate_intent",
    "retrieve_knowledge_detail",
    "query_data",
    "compose_answer",
    "local_validate",
    "review_answer",
    "decide_retry",
    "suggest_questions",
    "persist_answer",
)
_STEP_LABELS: Final[dict[str, str]] = {
    "load_context": "识别商家与会话上下文",
    "retrieve_knowledge_index": "读取业务知识索引",
    "classify_intent": "识别问题类型与业务域",
    "understand_intent": "结构化理解问题",
    "validate_intent": "校验查询意图",
    "retrieve_knowledge_detail": "读取业务知识正文",
    "query_data": "查询经营数据",
    "compose_answer": "整理回答",
    "local_validate": "本地校验回答",
    "review_answer": "复核回答质量",
    "decide_retry": "判断是否需要重试",
    "suggest_questions": "生成推荐问题",
    "persist_answer": "保存本轮回答",
}


@dataclass(frozen=True)
class AgentRunResult:
    response: ChatResponse
    steps: list[ThinkingStep]
    query_result: QueryResult | None = None


class MerchantQaGraph:
    """以结构化意图、受控知识检索和受控经营查询驱动的商家问答图。"""

    def __init__(
        self,
        *,
        retrieval: KnowledgeRetrieval,
        intent_service_llm: LlmClient,
        catalog: MetricCatalog,
        max_llm_calls: int = 4,
        max_llm_tokens: int = 8_000,
        query_service: QueryServiceLike | None = None,
        merchant_id: UUID | None = None,
        answer_llm: LlmClient | None = None,
        reviewer_llm: LlmClient | None = None,
        answer_service: AnswerService | None = None,
        review_service: ReviewService | None = None,
        visualization_service: VisualizationService | None = None,
        node_timer: NodeTimerLike | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._intent_service = IntentService(intent_service_llm)
        self._catalog = catalog
        self._max_calls = max_llm_calls
        self._max_tokens = max_llm_tokens
        self._query_service = query_service
        self._merchant_id = merchant_id
        self._answer_llm = answer_llm
        self._reviewer_llm = reviewer_llm
        self._answer_service = answer_service or AnswerService()
        self._review_service = review_service or ReviewService()
        self._visualization_service = visualization_service or VisualizationService()
        self._node_timer = node_timer
        self._graph = self._build_graph()

    async def run(self, message: str, session_id: UUID) -> AgentRunResult:
        state = await self._graph.ainvoke(self._initial_state(message, session_id))
        final_state = cast(AgentState, state)
        response = self._response(final_state)
        return AgentRunResult(
            response=response,
            steps=final_state["steps"],
            query_result=final_state["query_result"],
        )

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)
        node_methods: dict[str, Callable[[AgentState], Awaitable[dict[str, object]]]] = {
            name: getattr(self, f"_{name}") for name in GRAPH_NODES
        }
        for name in GRAPH_NODES:
            graph.add_node(name, cast(Any, self._timed_node(name, node_methods[name])))
        graph.add_edge(START, "load_context")
        for source, target in pairwise(GRAPH_NODES):
            graph.add_edge(source, target)
        graph.add_edge("persist_answer", END)
        return graph.compile()

    def _timed_node(
        self, name: str, fn: Callable[[AgentState], Awaitable[dict[str, object]]]
    ) -> Callable[[AgentState], Awaitable[dict[str, object]]]:
        if self._node_timer is None:
            return fn
        node_timer = self._node_timer

        async def wrapper(state: AgentState) -> dict[str, object]:
            start = monotonic()
            try:
                return await fn(state)
            finally:
                node_timer.record_node_duration(name, monotonic() - start)

        return wrapper

    def _initial_state(self, message: str, session_id: UUID) -> AgentState:
        return {
            "request_id": str(uuid4()),
            "session_id": session_id,
            "question": message,
            "knowledge_index": None,
            "knowledge_detail": None,
            "initial_intent": None,
            "intent": None,
            "intent_validation": None,
            "metric_definition": None,
            "query_result": None,
            "query_error": None,
            "answer_facts": None,
            "candidate_answer": "",
            "visualization": None,
            "recommendations": [],
            "suggestions": [],
            "suggestion_alternates": [],
            "analysis_sources": [AnalysisSource.NONE],
            "quality_status": QualityStatus.NOT_RUN,
            "quality_notes": [],
            "attempt": 0,
            "degraded": False,
            "degraded_reason": None,
            "budget": LlmBudget(self._max_calls, self._max_tokens),
            "steps": [],
        }

    @staticmethod
    def _step(state: AgentState, node: str) -> dict[str, object]:
        return {"steps": [*state["steps"], ThinkingStep(label=_STEP_LABELS[node], node=node)]}

    async def _load_context(self, state: AgentState) -> dict[str, object]:
        return self._step(state, "load_context")

    async def _retrieve_knowledge_index(self, state: AgentState) -> dict[str, object]:
        return {
            **self._step(state, "retrieve_knowledge_index"),
            "knowledge_index": await self._retrieval.load_index(),
        }

    async def _classify_intent(self, state: AgentState) -> dict[str, object]:
        index = _required(state["knowledge_index"])
        initial = await self._intent_service.recognize(
            state["question"], index.text, state["budget"]
        )
        return {**self._step(state, "classify_intent"), "initial_intent": initial}

    async def _understand_intent(self, state: AgentState) -> dict[str, object]:
        initial = _required(state["initial_intent"])
        index = _required(state["knowledge_index"])
        outcome = await self._intent_service.understand(
            state["question"], initial, index.text, state["budget"], date.today()
        )
        return {
            **self._step(state, "understand_intent"),
            "intent": outcome.intent,
            "intent_validation": outcome.validation,
            "quality_notes": [*state["quality_notes"], *outcome.notes],
            "degraded": outcome.degraded,
            "degraded_reason": outcome.degraded_reason,
        }

    async def _validate_intent(self, state: AgentState) -> dict[str, object]:
        """把白名单校验的拒绝与截断结果透出为用户可见备注。

        校验本身在 IntentService.understand 内随结构化输出一起完成——拿到意图的
        那一刻就必须校验，不能先让未校验的意图在图里流动。
        """

        validation = state["intent_validation"]
        notes = list(state["quality_notes"])
        if validation is not None:
            notes.extend(validation.adjusted)
            notes.extend(validation.rejected)
        return {**self._step(state, "validate_intent"), "quality_notes": notes}

    async def _retrieve_knowledge_detail(self, state: AgentState) -> dict[str, object]:
        initial = _required(state["initial_intent"])
        intent = _required(state["intent"])
        detail = await self._retrieval.load_domain(initial.category, initial.intent_keywords)
        notes = list(state["quality_notes"])
        if detail.has_incomplete:
            notes.append("命中的知识资料尚未完整，回答仅基于现有内容")
        if not detail.matched:
            notes.append("未命中与当前问题相关的知识资料")
        # 口径检索放在正文层之后：三级检索的第三级要靠知识正文生成候选口径，
        # 而索引层只有目录词汇。节点顺序由计划 §10 固定，正文层在此才可用。
        metric: MetricPayload | None = None
        if intent.answer_mode is AnswerMode.METRIC:
            metric = await self._catalog.resolve(intent, detail.text, state["budget"])
        return {
            **self._step(state, "retrieve_knowledge_detail"),
            "knowledge_detail": detail,
            "metric_definition": metric,
            "quality_notes": notes,
        }

    async def _query_data(self, state: AgentState) -> dict[str, object]:
        intent = _required(state["intent"])
        if self._query_service is None or self._merchant_id is None:
            # 未注入查询服务时保持 B3 的可见降级，而不是假装查过。
            return self._step(state, "query_data")
        if intent.answer_mode not in {AnswerMode.METRIC, AnswerMode.DETAIL}:
            return self._step(state, "query_data")

        # REFUND 类别下退款/退货二次路由要靠分类阶段的关键词；初始意图理论上
        # 此时必已产出（`classify_intent` 在图里排在 `query_data` 之前），但
        # 状态类型是 Optional，缺失时按「没有关键词信号」处理，不额外报错。
        initial = state["initial_intent"]
        keywords = initial.intent_keywords if initial is not None else ()

        try:
            result = await self._query_service.execute(
                MerchantContext(merchant_id=self._merchant_id),
                intent,
                now=datetime.now(UTC),
                keywords=keywords,
            )
        except UnsupportedQueryError as error:
            return {
                **self._step(state, "query_data"),
                "query_error": error.reason,
                "quality_notes": [*state["quality_notes"], error.reason],
            }
        return {
            **self._step(state, "query_data"),
            "query_result": result,
            "quality_notes": [*state["quality_notes"], *result.notes],
        }

    async def _compose_answer(self, state: AgentState) -> dict[str, object]:
        intent = _required(state["intent"])
        detail = state["knowledge_detail"]
        # `compose_answer` 排在 `query_data` 之后，所以这里能看到本轮到底查没查到
        # 数据。查到了还说「查询将在后续阶段接入」，就是一边给结果一边否认查询
        # 发生过——用户会连旁边的真实数字一起不信（AGENTS.md R7）。
        queried = state["query_result"] is not None
        answer = "已完成结构化理解。"
        if queried and intent.answer_mode in {AnswerMode.METRIC, AnswerMode.DETAIL}:
            facts = AnswerFacts(
                question=state["question"],
                metric=state["metric_definition"],
                query_result=_required(state["query_result"]),
            )
            if self._answer_llm is not None:
                composed = await self._answer_service.compose(
                    facts,
                    self._answer_llm,
                    state["budget"],
                )
                return {
                    **self._step(state, "compose_answer"),
                    "answer_facts": facts,
                    "candidate_answer": composed.draft.answer,
                    "recommendations": composed.draft.recommendations,
                    "visualization": self._visualization_service.build(
                        facts.query_result,
                        facts.metric,
                    ),
                    "analysis_sources": [AnalysisSource.DATABASE],
                    "quality_status": (
                        QualityStatus.DEGRADED if composed.degraded else QualityStatus.NOT_RUN
                    ),
                    "quality_notes": [*state["quality_notes"], *composed.notes],
                    "attempt": 1 if composed.degraded else 0,
                    "degraded": state["degraded"] or composed.degraded,
                    "degraded_reason": (
                        "回答生成服务暂不可用，已返回受控数据摘要。"
                        if composed.degraded
                        else state["degraded_reason"]
                    ),
                }
        if intent.answer_mode is AnswerMode.METRIC:
            answer = (
                "已按识别到的指标口径和时间范围查询经营数据，结果见下方数据与查询计划；"
                "对数字的解读与图表将在后续阶段补齐。"
                if queried
                # 降级分支说「尚未执行」是真话，保留；但不能承诺「将在某阶段接入」——
                # 受控查询本身已经交付了，这次没有数据是本次请求的问题，
                # 具体原因在 degraded_reason 里。
                else "已识别指标和查询范围，本次尚未执行经营数据查询。"
            )
        elif intent.answer_mode is AnswerMode.DETAIL:
            answer = (
                "已按识别到的明细范围查询经营数据，结果见下方明细与查询计划；"
                "对明细的解读与导出将在后续阶段补齐。"
                if queried
                else "已识别明细查询意图，本次尚未执行经营数据查询。"
            )
        elif intent.answer_mode is AnswerMode.RULE:
            answer = _knowledge_answer(detail)
        elif intent.answer_mode is AnswerMode.INVALID:
            answer = "该请求包含不受支持或不安全的查询字段，无法执行。"
        return {**self._step(state, "compose_answer"), "candidate_answer": answer}

    async def _local_validate(self, state: AgentState) -> dict[str, object]:
        # AnswerService 在模型草稿解析后立即校验；本节点保留可见轨迹。
        return self._step(state, "local_validate")

    async def _review_answer(self, state: AgentState) -> dict[str, object]:
        facts = state["answer_facts"]
        if facts is None or self._reviewer_llm is None or state["degraded"]:
            return self._step(state, "review_answer")

        draft = _draft_from_state(state)
        first = await self._review_service.review(
            draft,
            self._answer_service.facts_json(facts),
            self._reviewer_llm,
            state["budget"],
        )
        if first.degraded:
            return _review_degraded(state, first.notes, 1)
        if first.verdict.passed:
            return {
                **self._step(state, "review_answer"),
                "quality_status": QualityStatus.PASSED,
                "attempt": 1,
            }

        retried = await self._answer_service.compose(
            facts, self._answer_llm_or_raise(), state["budget"]
        )
        if retried.degraded:
            return _review_degraded(state, retried.notes, 2)
        second = await self._review_service.review(
            retried.draft,
            self._answer_service.facts_json(facts),
            self._reviewer_llm,
            state["budget"],
        )
        if second.degraded:
            return _review_degraded(state, second.notes, 2)
        return {
            **self._step(state, "review_answer"),
            "candidate_answer": retried.draft.answer,
            "recommendations": retried.draft.recommendations,
            "quality_status": QualityStatus.PASSED
            if second.verdict.passed
            else QualityStatus.FAILED,
            "attempt": 2,
            "quality_notes": [*state["quality_notes"], *second.verdict.issues],
        }

    async def _decide_retry(self, state: AgentState) -> dict[str, object]:
        # 重试已在 review_answer 内受 MAX_REVIEW_ATTEMPTS=2 限制执行。
        return self._step(state, "decide_retry")

    def _answer_llm_or_raise(self) -> LlmClient:
        if self._answer_llm is None:
            raise RuntimeError("回答模型未注入")
        return self._answer_llm

    async def _suggest_questions(self, state: AgentState) -> dict[str, object]:
        intent = _required(state["intent"])
        suggested = suggestions_for(intent.category, intent.answer_mode)
        return {
            **self._step(state, "suggest_questions"),
            "suggestions": suggested.current,
            "suggestion_alternates": suggested.alternates,
        }

    async def _persist_answer(self, state: AgentState) -> dict[str, object]:
        # 真实持久化由 ChatService 在商家范围与幂等保护内完成。
        return self._step(state, "persist_answer")

    def _response(self, state: AgentState) -> ChatResponse:
        intent = _required(state["intent"])
        if intent.answer_mode is AnswerMode.METRIC:
            metric = state["metric_definition"] or _unverified_metric(intent.metric)
            outcome = _query_outcome(
                state,
                fallback_query_plan="已校验结构化查询意图，尚未执行数据查询。",
                fallback_note="当前未执行经营数据查询。",
                fallback_reason=_QUERY_SERVICE_UNAVAILABLE,
            )
            notes = list(outcome.notes)
            if metric.generated and metric.notice is not None:
                # 生成口径必须带待核验说明，否则用户会把模型猜的口径当成正式口径。
                notes.append(metric.notice)
            return ChatResponse(
                id=uuid4(),
                session_id=state["session_id"],
                answer=state["candidate_answer"],
                answer_mode=AnswerMode.METRIC,
                category=intent.category,
                thinking_steps=state["steps"],
                quality_status=_response_quality(state, outcome),
                quality_attempts=state["attempt"] if outcome.succeeded else 0,
                quality_notes=notes,
                analysis_sources=_response_sources(state, outcome),
                degraded=_response_degraded(state, outcome),
                degraded_reason=_response_degraded_reason(state, outcome),
                suggestions=state["suggestions"],
                suggestion_alternates=state["suggestion_alternates"],
                query_plan=outcome.query_plan,
                metric_code=metric.metric_code,
                metric_display_name=metric.display_name,
                metric_unit=metric.unit,
                metric_definition=metric.definition,
                metric_source=metric.source,
                metric_owner=metric.owner,
                metric_status=MetricStatus(metric.status),
                data_rows=outcome.data_rows,
                total_rows=outcome.total_rows,
                truncated=outcome.truncated,
                visualization=state["visualization"] or Visualization(enabled=False),
                recommendations=state["recommendations"]
                or _metric_recommendations(outcome, metric),
            )

        if intent.answer_mode is AnswerMode.DETAIL:
            export_id = uuid4()
            outcome = _query_outcome(
                state,
                fallback_query_plan="已校验明细查询意图，尚未执行数据查询。",
                fallback_note="当前未执行经营明细查询。",
                fallback_reason=_QUERY_SERVICE_UNAVAILABLE,
            )
            return ChatResponse(
                id=uuid4(),
                session_id=state["session_id"],
                answer=state["candidate_answer"],
                answer_mode=AnswerMode.DETAIL,
                category=intent.category,
                thinking_steps=state["steps"],
                quality_status=_response_quality(state, outcome),
                quality_attempts=state["attempt"] if outcome.succeeded else 0,
                quality_notes=outcome.notes,
                analysis_sources=_response_sources(state, outcome),
                degraded=_response_degraded(state, outcome),
                degraded_reason=_response_degraded_reason(state, outcome),
                suggestions=state["suggestions"],
                suggestion_alternates=state["suggestion_alternates"],
                query_plan=outcome.query_plan,
                data_rows=outcome.data_rows,
                total_rows=outcome.total_rows,
                truncated=outcome.truncated,
                # 导出端点属于 B6：这里仍只登记一个占位 id/url，
                # QueryResult.export_spec（真正的表/列/时间范围）留给 B6 消费。
                export=ExportInfo(
                    id=export_id,
                    url=f"/api/exports/{export_id}",
                    expires_at=datetime.now(UTC),
                ),
                recommendations=state["recommendations"] or _detail_recommendations(outcome),
            )

        mode = (
            intent.answer_mode
            if intent.answer_mode in {AnswerMode.RULE, AnswerMode.IDENTITY, AnswerMode.INVALID}
            else AnswerMode.CHAT
        )
        if mode is AnswerMode.IDENTITY:
            # 受控查询只覆盖经营数据，商家资料查询属于后续阶段；
            # 保持契约所需的数据型空结果并明确降级，不返回空数组假装查过。
            return ChatResponse(
                id=uuid4(),
                session_id=state["session_id"],
                answer=state["candidate_answer"],
                answer_mode=mode,
                category=intent.category,
                thinking_steps=state["steps"],
                quality_status=QualityStatus.DEGRADED,
                quality_attempts=0,
                quality_notes=[*state["quality_notes"], "当前未执行商家资料查询。"],
                analysis_sources=[AnalysisSource.FALLBACK],
                degraded=True,
                degraded_reason="当前版本尚未开放商家资料查询",
                suggestions=state["suggestions"],
                suggestion_alternates=state["suggestion_alternates"],
                query_plan=QueryPlanSummary(summary="已校验身份资料查询意图，尚未执行数据查询。"),
                data_rows=[],
                total_rows=0,
                truncated=False,
            )
        knowledge_detail = state["knowledge_detail"]
        sources = (
            [AnalysisSource.KNOWLEDGE]
            if mode is AnswerMode.RULE and knowledge_detail is not None and knowledge_detail.matched
            else [AnalysisSource.FALLBACK]
            if state["degraded"]
            else [AnalysisSource.NONE]
        )
        return ChatResponse(
            id=uuid4(),
            session_id=state["session_id"],
            answer=state["candidate_answer"],
            answer_mode=mode,
            category=intent.category,
            thinking_steps=state["steps"],
            quality_status=(QualityStatus.DEGRADED if state["degraded"] else QualityStatus.NOT_RUN),
            quality_attempts=0,
            quality_notes=state["quality_notes"],
            analysis_sources=sources,
            degraded=state["degraded"],
            degraded_reason=state["degraded_reason"],
            suggestions=state["suggestions"],
            suggestion_alternates=state["suggestion_alternates"],
        )


def _required[T](value: T | None) -> T:
    if value is None:
        raise RuntimeError("问答图状态缺少必填字段")
    return value


@dataclass(frozen=True)
class _QueryOutcome:
    """METRIC/DETAIL 两个分支共用的「查询结果如何填进响应」计算结果。"""

    query_plan: QueryPlanSummary
    data_rows: list[dict[str, object]]
    total_rows: int
    truncated: bool
    analysis_sources: list[AnalysisSource]
    degraded: bool
    degraded_reason: str | None
    quality_status: QualityStatus
    notes: list[str]
    #: 真查询成功了——`recommendations` 靠它选文案，不能对着降级结果说「已查到」，
    #: 也不能对着真数据说「尚未执行」。
    succeeded: bool


def _draft_from_state(state: AgentState) -> AnswerDraft:
    return AnswerDraft(
        answer=state["candidate_answer"],
        recommendations=state["recommendations"],
    )


def _review_degraded(state: AgentState, notes: list[str], attempt: int) -> dict[str, object]:
    return {
        **MerchantQaGraph._step(state, "review_answer"),
        "quality_status": QualityStatus.DEGRADED,
        "attempt": attempt,
        "quality_notes": [*state["quality_notes"], *notes],
        "degraded": True,
        "degraded_reason": "回答质量复核服务暂不可用，已返回受控数据摘要。",
    }


def _response_quality(state: AgentState, outcome: _QueryOutcome) -> QualityStatus:
    return state["quality_status"] if outcome.succeeded else outcome.quality_status


def _response_sources(state: AgentState, outcome: _QueryOutcome) -> list[AnalysisSource]:
    if outcome.succeeded and state["analysis_sources"] != [AnalysisSource.NONE]:
        return state["analysis_sources"]
    return outcome.analysis_sources


def _response_degraded(state: AgentState, outcome: _QueryOutcome) -> bool:
    return state["degraded"] if outcome.succeeded else outcome.degraded


def _response_degraded_reason(state: AgentState, outcome: _QueryOutcome) -> str | None:
    return state["degraded_reason"] if outcome.succeeded else outcome.degraded_reason


def _query_outcome(
    state: AgentState,
    *,
    fallback_query_plan: str,
    fallback_note: str,
    fallback_reason: str,
) -> _QueryOutcome:
    """把 `_query_data` 节点的结果翻译成响应字段。

    有 `query_result` 就是真查询成功；没有的话要区分「查询被拒」（`query_error`
    非空，拒绝原因来自 `UnsupportedQueryError.reason`，可以直接展示）和「根本
    没注入查询服务」（保留 B3 的通用降级文案）两种情况，但两者对用户来说都是
    同一种可见降级，不能悄悄返回空数组假装没有数据。
    """

    query_result = state["query_result"]
    if query_result is not None:
        return _QueryOutcome(
            query_plan=QueryPlanSummary(summary="；".join(query_result.plan_steps)),
            data_rows=_json_rows(query_result.rows),
            total_rows=query_result.total_rows,
            truncated=query_result.truncated,
            analysis_sources=[AnalysisSource.DATABASE],
            degraded=False,
            degraded_reason=None,
            quality_status=QualityStatus.NOT_RUN,
            notes=list(state["quality_notes"]),
            succeeded=True,
        )
    return _QueryOutcome(
        query_plan=QueryPlanSummary(summary=fallback_query_plan),
        data_rows=[],
        total_rows=0,
        truncated=False,
        analysis_sources=[AnalysisSource.FALLBACK],
        degraded=True,
        degraded_reason=state["query_error"] or fallback_reason,
        quality_status=QualityStatus.DEGRADED,
        notes=[*state["quality_notes"], fallback_note],
        succeeded=False,
    )


def _metric_recommendations(outcome: _QueryOutcome, metric: MetricPayload) -> list[Recommendation]:
    """METRIC 的 `recommendations`：查到了就不能再说「尚未执行」。

    这两条建议本身不是 B5 的「有洞察的分析」——它们不解读数字，只核对范围和
    口径，`evidence` 里出现的行数直接来自 `outcome.total_rows`（真实查询结果），
    不编造业务结论。B5 才会在这基础上生成有分析价值的建议。
    """

    if not outcome.succeeded:
        return [
            # 用户看不懂内部阶段代号，也不该被告诉「功能还没上线」——受控查询已经
            # 交付，这次没有数据是本次请求的问题，具体原因在 degraded_reason 里。
            Recommendation(
                title="本次没有取到经营数据",
                evidence="已完成结构化意图校验，但尚未执行经营数据查询。",
                action="按上方降级说明调整问题后重试。",
            ),
            Recommendation(
                title="核对指标口径",
                evidence=f"已识别指标代码：{metric.metric_code}。",
                action="确认日期范围和维度后再查询。",
            ),
        ]
    return [
        Recommendation(
            title="核对查询范围",
            evidence=f"本次查询返回 {outcome.total_rows} 行数据。",
            action="确认日期范围和维度是否覆盖你想了解的口径。",
        ),
        Recommendation(
            title="核对指标口径",
            evidence=f"已识别指标代码：{metric.metric_code}。",
            action="如口径与预期不符，请调整问题后重新查询。",
        ),
    ]


def _detail_recommendations(outcome: _QueryOutcome) -> list[Recommendation]:
    """DETAIL 的 `recommendations`：同上，查到了就不能再说「尚未执行」。"""

    if not outcome.succeeded:
        return [
            Recommendation(
                title="本次没有取到明细数据",
                evidence="已完成结构化意图校验，但尚未执行经营明细查询。",
                action="按上方降级说明调整问题后重试。",
            ),
            Recommendation(
                title="补充筛选条件",
                evidence="当前没有可展示的明细数据。",
                action="补充日期或商品条件后再查询。",
            ),
        ]
    scope_evidence = (
        f"本次预览返回 {outcome.total_rows} 行，已达到预览上限，可能还有更多记录。"
        if outcome.truncated
        else f"本次预览返回 {outcome.total_rows} 行，已覆盖本次查询的全部结果。"
    )
    return [
        Recommendation(
            title="核对查询范围",
            evidence=scope_evidence,
            action="确认筛选条件是否覆盖你想查看的记录。",
        ),
        Recommendation(
            title="导出完整明细",
            evidence="预览行数受上限约束，导出可拿到完整明细文件。",
            action="如需完整明细用于外部处理，可使用导出功能。",
        ),
    ]


def _json_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Decimal 转字符串保精度，日期转 ISO 8601。float 会丢分。"""

    converted: list[dict[str, object]] = []
    for row in rows:
        converted.append(
            {
                key: (
                    str(value)
                    if isinstance(value, Decimal)
                    else value.isoformat()
                    if isinstance(value, date | datetime)
                    else value
                )
                for key, value in row.items()
            }
        )
    return converted


def _knowledge_answer(detail: KnowledgeResult | None) -> str:
    """将受控检索结果写入规则回答，保留可核验的文档来源。"""

    if detail is None or not detail.matched:
        return "未命中与当前问题相关的知识资料，暂不能依据知识库给出规则结论。"

    hits = detail.hits
    excerpts = [
        f"- {hit.content.strip()}\n  来源：{hit.source_path}" for hit in hits if hit.content.strip()
    ]
    if not excerpts:
        return "未命中可展示正文的知识资料，暂不能依据知识库给出规则结论。"
    return "根据知识库检索到的资料：\n" + "\n".join(excerpts)


def _unverified_metric(metric_code: str | None) -> MetricPayload:
    return MetricPayload(
        metric_code=metric_code or "unknown_metric",
        display_name="待确认指标",
        unit="",
        definition="未命中正式指标目录，口径需人工确认后才能作为正式口径使用。",
        source="Borough 指标目录",
        owner="经营分析组",
        status=MetricStatus.UNVERIFIED.value,
        generated=False,
        notice=None,
    )
