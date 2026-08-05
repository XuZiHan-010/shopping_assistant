"""B3 商家问答 LangGraph。

图的节点顺序与后端设计 §10 一致。B4/B5 尚未实现的数据查询与质量复核节点保留为
可见的 passthrough，保证 SSE 处理轨迹与后续阶段兼容，而不伪装成已完成的数据分析。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
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
from app.services.safe_query import QueryResult, UnsupportedQueryError
from app.services.suggested_questions import suggestions_for


class QueryServiceLike(Protocol):
    """`_query_data` 需要的最小接口；真实实现是 B4 的 `SafeQueryService`。"""

    async def execute(
        self, context: MerchantContext, intent: QueryIntent, *, now: datetime
    ) -> QueryResult: ...


MAX_REVIEW_ATTEMPTS: Final[int] = 2
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


class MerchantQaGraph:
    """以结构化意图和受控知识检索驱动的 B3 问答图。"""

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
    ) -> None:
        self._retrieval = retrieval
        self._intent_service = IntentService(intent_service_llm)
        self._catalog = catalog
        self._max_calls = max_llm_calls
        self._max_tokens = max_llm_tokens
        self._query_service = query_service
        self._merchant_id = merchant_id
        self._graph = self._build_graph()

    async def run(self, message: str, session_id: UUID) -> AgentRunResult:
        state = await self._graph.ainvoke(self._initial_state(message, session_id))
        final_state = cast(AgentState, state)
        response = self._response(final_state)
        return AgentRunResult(response=response, steps=final_state["steps"])

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("load_context", self._load_context)
        graph.add_node("retrieve_knowledge_index", self._retrieve_knowledge_index)
        graph.add_node("classify_intent", self._classify_intent)
        graph.add_node("understand_intent", self._understand_intent)
        graph.add_node("validate_intent", self._validate_intent)
        graph.add_node("retrieve_knowledge_detail", self._retrieve_knowledge_detail)
        graph.add_node("query_data", self._query_data)
        graph.add_node("compose_answer", self._compose_answer)
        graph.add_node("local_validate", self._local_validate)
        graph.add_node("review_answer", self._review_answer)
        graph.add_node("decide_retry", self._decide_retry)
        graph.add_node("suggest_questions", self._suggest_questions)
        graph.add_node("persist_answer", self._persist_answer)
        graph.add_edge(START, "load_context")
        for source, target in pairwise(GRAPH_NODES):
            graph.add_edge(source, target)
        graph.add_edge("persist_answer", END)
        return graph.compile()

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

        try:
            result = await self._query_service.execute(
                MerchantContext(merchant_id=self._merchant_id),
                intent,
                now=datetime.now(UTC),
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
        answer = "已完成结构化理解。"
        if intent.answer_mode is AnswerMode.METRIC:
            answer = "已识别指标和查询范围；经营数据查询将在 B4 接入。"
        elif intent.answer_mode is AnswerMode.DETAIL:
            answer = "已识别明细查询意图；经营数据查询将在 B4 接入。"
        elif intent.answer_mode is AnswerMode.RULE:
            answer = _knowledge_answer(detail)
        elif intent.answer_mode is AnswerMode.INVALID:
            answer = "该请求包含不受支持或不安全的查询字段，无法执行。"
        return {**self._step(state, "compose_answer"), "candidate_answer": answer}

    async def _local_validate(self, state: AgentState) -> dict[str, object]:
        # 占位：B5 的本地答案证据校验尚未接入。
        return self._step(state, "local_validate")

    async def _review_answer(self, state: AgentState) -> dict[str, object]:
        # 占位：B5 的独立 Reviewer 尚未接入。
        return self._step(state, "review_answer")

    async def _decide_retry(self, state: AgentState) -> dict[str, object]:
        # B3 不执行 Reviewer；该显式上限为 B5 条件分支预留。
        return self._step(state, "decide_retry")

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
                fallback_reason="经营数据安全查询将在 B4 接入",
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
                quality_status=outcome.quality_status,
                quality_attempts=0,
                quality_notes=notes,
                analysis_sources=outcome.analysis_sources,
                degraded=outcome.degraded,
                degraded_reason=outcome.degraded_reason,
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
                # 图表仍是 B5 的工作：这里只保证契约必填字段有值，不据真实数据生成
                # 图表——那会预支 B5 尚未做的分析。`recommendations` 不属于这条限制：
                # 它必须如实反映「查没查到数据」，见 `_metric_recommendations`。
                visualization=Visualization(enabled=False),
                recommendations=_metric_recommendations(outcome, metric),
            )

        if intent.answer_mode is AnswerMode.DETAIL:
            export_id = uuid4()
            outcome = _query_outcome(
                state,
                fallback_query_plan="已校验明细查询意图，尚未执行数据查询。",
                fallback_note="当前未执行经营明细查询。",
                fallback_reason="经营数据安全查询将在 B4 接入",
            )
            return ChatResponse(
                id=uuid4(),
                session_id=state["session_id"],
                answer=state["candidate_answer"],
                answer_mode=AnswerMode.DETAIL,
                category=intent.category,
                thinking_steps=state["steps"],
                quality_status=outcome.quality_status,
                quality_attempts=0,
                quality_notes=outcome.notes,
                analysis_sources=outcome.analysis_sources,
                degraded=outcome.degraded,
                degraded_reason=outcome.degraded_reason,
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
                recommendations=_detail_recommendations(outcome),
            )

        mode = (
            intent.answer_mode
            if intent.answer_mode in {AnswerMode.RULE, AnswerMode.IDENTITY, AnswerMode.INVALID}
            else AnswerMode.CHAT
        )
        if mode is AnswerMode.IDENTITY:
            # B4 尚无商家资料查询；保持契约所需的数据型空结果并明确降级。
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
                degraded_reason="商家资料查询将在 B4 接入",
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
            Recommendation(
                title="等待数据查询接入",
                evidence="B3 已完成结构化意图校验，尚未执行经营数据查询。",
                action="B4 接入受控查询后展示经营结果。",
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
                title="等待明细查询接入",
                evidence="B3 已完成结构化意图校验，尚未执行经营数据查询。",
                action="B4 接入受控查询后展示明细。",
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
        definition="未命中正式指标目录，等待 B4 数据查询前人工确认。",
        source="Borough 指标目录",
        owner="经营分析组",
        status=MetricStatus.UNVERIFIED.value,
        generated=False,
        notice=None,
    )
