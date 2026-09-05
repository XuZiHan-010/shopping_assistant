"""商家问答 LangGraph。

图的节点顺序与后端设计 §10 一致。`query_data` 在注入了查询服务时执行真实的
受控经营查询；质量复核相关节点仍是可见的 passthrough，保证 SSE 处理轨迹与
后续阶段兼容，而不伪装成已完成的数据分析。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from time import monotonic
from typing import Any, Final, Protocol, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from app.agent import prefilter
from app.agent.state import AgentState
from app.core.security import MerchantContext
from app.intent.models import QueryIntent
from app.intent.service import IntentService
from app.knowledge.retrieval import KnowledgeResult, KnowledgeRetrieval, KnowledgeSource
from app.llm.client import LlmBudget, LlmClient
from app.localization.catalog import localize_catalog_value
from app.localization.locales import SupportedLocale
from app.metrics.catalog import MetricCatalog, MetricPayload
from app.schemas.chat import (
    AnalysisSource,
    AnswerMode,
    ChatResponse,
    ExportInfo,
    MetricDefinitionSource,
    MetricStatus,
    QualityStatus,
    QueryPlanSummary,
    QuestionCategory,
    Recommendation,
    ThinkingStep,
    Visualization,
)
from app.services.answer_service import AnswerFacts, AnswerService
from app.services.quality_loop import QualityLoop
from app.services.quality_types import DegradeReason
from app.services.review_service import ReviewService
from app.services.safe_query import QueryResult, UnsupportedQueryError
from app.services.suggested_questions import suggestions_for
from app.services.visualization_service import VisualizationService

logger = logging.getLogger(__name__)


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


class HistoryQuestionsLike(Protocol):
    """`_suggest_questions` 读取商家历史高频问题需要的最小接口。"""

    async def top_category_questions(
        self, *, merchant_id: UUID, category: str, limit: int
    ) -> list[str]: ...


class SessionHistoryLike(Protocol):
    """`_prefilter_question` 判断本会话是否已有历史轮次的最小接口。"""

    async def has_assistant_message(self, merchant_id: UUID, conversation_id: UUID) -> bool: ...


def _text(zh: str, en: str, locale: SupportedLocale) -> str:
    """两语言字面量的最小选取器：graph.py 里绝大多数文案是固定、非参数化的
    整句，不值得为每一句都单独登记进 `app.localization.catalog`（那张表是给
    「多处业务复用同一句」的场景设计的）。调用点直接内联中英文原句，locale
    在这里做最后一步选取，改文案时中英文永远在同一处、不会漂移。"""

    return en if locale is SupportedLocale.EN_US else zh


#: 只在「查询服务根本没注入」时用（查询被拒时 `degraded_reason` 取
#: `UnsupportedQueryError.reason`，那条更具体）。不写「将在某阶段接入」——受控查询
#: 本身已经交付，这么说会让用户以为功能还没上线，而实际是这次请求没能查成。
_QUERY_SERVICE_UNAVAILABLE: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: "经营数据查询服务当前不可用，本次未执行查询",
    SupportedLocale.EN_US: (
        "The business data query service is currently unavailable; no query was "
        "executed this time."
    ),
}
#: 闸门拒答文案：说明范围而非报错，避免用户把设计内的拒绝当成系统故障（R7、design.md D7）。
#: Task 5 登记的中文原句已经原样保留在这里（`zh-CN` 分支），与
#: `app.localization.catalog._PREFILTER_REJECTION_MESSAGES` 的词典 key 逐字一致；
#: Task 6 在这里补上按 locale 选取的英文分支，不改变中文原句本身。
_PREFILTER_REJECTION_MESSAGES: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: (
        "我是 Borough 商家 AI 助手，只能回答与您店铺经营相关的问题，"
        "例如成交额、订单、退款、商品或平台规则。换个和经营相关的问法试试？"
    ),
    SupportedLocale.EN_US: (
        "I'm the Borough Merchant AI Assistant, and I can only answer questions "
        "related to your store's operations, such as GMV, orders, refunds, "
        "products, or platform rules. Please try rephrasing your question to "
        "relate to your business."
    ),
}
#: 向后兼容：历史上以模块级常量形式存在的中文原句，供仍按旧写法直接比对
#: 字面量的调用点（如 catalog 的登记注释）使用，值与
#: `_PREFILTER_REJECTION_MESSAGES[SupportedLocale.ZH_CN]` 逐字相同。
_PREFILTER_REJECTION_MESSAGE: Final[str] = _PREFILTER_REJECTION_MESSAGES[SupportedLocale.ZH_CN]
GRAPH_NODES: Final[tuple[str, ...]] = (
    "load_context",
    "retrieve_knowledge_index",
    "prefilter_question",
    "classify_intent",
    "understand_intent",
    "validate_intent",
    "retrieve_knowledge_detail",
    "query_data",
    "compose_answer",
    "quality_loop",
    "suggest_questions",
    "persist_answer",
)
_STEP_LABELS: Final[dict[str, dict[SupportedLocale, str]]] = {
    "load_context": {
        SupportedLocale.ZH_CN: "识别商家与会话上下文",
        SupportedLocale.EN_US: "Identifying merchant and conversation context",
    },
    "retrieve_knowledge_index": {
        SupportedLocale.ZH_CN: "读取业务知识索引",
        SupportedLocale.EN_US: "Loading the business knowledge index",
    },
    "prefilter_question": {
        SupportedLocale.ZH_CN: "判定问题范围",
        SupportedLocale.EN_US: "Determining question scope",
    },
    "classify_intent": {
        SupportedLocale.ZH_CN: "识别问题类型与业务域",
        SupportedLocale.EN_US: "Classifying question type and business domain",
    },
    "understand_intent": {
        SupportedLocale.ZH_CN: "结构化理解问题",
        SupportedLocale.EN_US: "Structuring the question intent",
    },
    "validate_intent": {
        SupportedLocale.ZH_CN: "校验查询意图",
        SupportedLocale.EN_US: "Validating the query intent",
    },
    "retrieve_knowledge_detail": {
        SupportedLocale.ZH_CN: "读取业务知识正文",
        SupportedLocale.EN_US: "Loading business knowledge details",
    },
    "query_data": {
        SupportedLocale.ZH_CN: "查询经营数据",
        SupportedLocale.EN_US: "Querying business data",
    },
    "compose_answer": {
        SupportedLocale.ZH_CN: "整理回答",
        SupportedLocale.EN_US: "Composing the answer",
    },
    "quality_loop": {
        SupportedLocale.ZH_CN: "校验并复核回答质量",
        SupportedLocale.EN_US: "Validating and reviewing answer quality",
    },
    "suggest_questions": {
        SupportedLocale.ZH_CN: "生成推荐问题",
        SupportedLocale.EN_US: "Generating suggested questions",
    },
    "persist_answer": {
        SupportedLocale.ZH_CN: "保存本轮回答",
        SupportedLocale.EN_US: "Saving this answer",
    },
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
        quality_max_attempts: int = 3,
        visualization_service: VisualizationService | None = None,
        node_timer: NodeTimerLike | None = None,
        history_questions: HistoryQuestionsLike | None = None,
        prefilter_enabled: bool = False,
        prefilter_min_score: int = 3,
        session_history: SessionHistoryLike | None = None,
        localization_budget: LlmBudget | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._intent_service = IntentService(intent_service_llm)
        self._catalog = catalog
        self._max_calls = max_llm_calls
        self._max_tokens = max_llm_tokens
        self._query_service = query_service
        self._merchant_id = merchant_id
        # 默认关闭：裸构造（大量既有单测的写法）不应该因为新增闸门而意外拒答，
        # 真实部署由 `api/dependencies.py` 按 `Settings.question_prefilter_enabled`
        # 显式打开（design.md D5）。
        self._prefilter_enabled = prefilter_enabled
        self._prefilter_min_score = prefilter_min_score
        self._session_history = session_history
        self._answer_llm = answer_llm
        self._reviewer_llm = reviewer_llm
        self._answer_service = answer_service or AnswerService()
        self._quality_loop_service = QualityLoop(
            max_attempts=quality_max_attempts,
            answer_service=self._answer_service,
            review_service=review_service,
        )
        self._visualization_service = visualization_service or VisualizationService()
        self._node_timer = node_timer
        self._history_questions = history_questions
        #: 跨语言知识召回查询规范化调用专用的独立预算——与本图其余节点共享的
        #: `state["budget"]`（AGENT 用途）区分开，不挤占问答本身的调用额度
        #: （与 `Settings.localization_max_calls_per_request` 同一原则，见
        #: `app.core.config`）。未注入时给一个「0 次调用」的哑对象：
        #: `KnowledgeRetrieval` 只有在真正拿到 `localizer` 时才会用到它，
        #: 而没注入 `localizer` 的既有构造点（裸构造、大量既有单测）永远不会
        #: 走到这条路径，这里的默认值只是让类型保持非空、不引入运行时分支。
        self._localization_budget = localization_budget or LlmBudget(0, 0)
        self._graph = self._build_graph()

    async def run(
        self,
        message: str,
        session_id: UUID,
        *,
        locale: SupportedLocale = SupportedLocale.ZH_CN,
    ) -> AgentRunResult:
        state = await self._graph.ainvoke(self._initial_state(message, session_id, locale))
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
            # `prefilter_question` 的出边不是线性的：拒绝时要跳过全部 LLM 驱动的
            # 节点直达 `suggest_questions`（design.md D1），下面单独用条件边覆盖。
            if source == "prefilter_question":
                continue
            graph.add_edge(source, target)
        graph.add_conditional_edges(
            "prefilter_question",
            self._route_after_prefilter,
            {"classify_intent": "classify_intent", "suggest_questions": "suggest_questions"},
        )
        graph.add_edge("persist_answer", END)
        return graph.compile()

    @staticmethod
    def _route_after_prefilter(state: AgentState) -> str:
        decision = state["prefilter_decision"]
        # decision 为 None 理论上不会发生（节点总会写入），fail open 仍然放行。
        if decision is None or decision.allowed:
            return "classify_intent"
        return "suggest_questions"

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

    def _initial_state(
        self, message: str, session_id: UUID, locale: SupportedLocale
    ) -> AgentState:
        return {
            "request_id": str(uuid4()),
            "session_id": session_id,
            "question": message,
            "locale": locale,
            "retrieval_queries": [],
            "knowledge_index": None,
            "knowledge_detail": None,
            "prefilter_decision": None,
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
        label = _STEP_LABELS[node][state["locale"]]
        return {"steps": [*state["steps"], ThinkingStep(label=label, node=node)]}

    async def _load_context(self, state: AgentState) -> dict[str, object]:
        return self._step(state, "load_context")

    async def _retrieve_knowledge_index(self, state: AgentState) -> dict[str, object]:
        return {
            **self._step(state, "retrieve_knowledge_index"),
            "knowledge_index": await self._retrieval.load_index(),
        }

    async def _prefilter_question(self, state: AgentState) -> dict[str, object]:
        session_has_prior_turn = False
        if self._session_history is not None and self._merchant_id is not None:
            try:
                session_has_prior_turn = await self._session_history.has_assistant_message(
                    self._merchant_id, state["session_id"]
                )
            except Exception:
                # 会话历史查询失败不该让本轮问答中断；按「无历史」处理，最坏结果
                # 只是本该跳过的判定又跑了一次，不会误拒。
                logger.warning("闸门读取会话历史失败，按无历史处理", exc_info=True)

        decision = await prefilter.decide(
            state["question"],
            enabled=self._prefilter_enabled,
            min_score=self._prefilter_min_score,
            session_has_prior_turn=session_has_prior_turn,
            score_question=self._retrieval.score_question,
        )
        result: dict[str, object] = {
            **self._step(state, "prefilter_question"),
            "prefilter_decision": decision,
        }
        if not decision.allowed:
            # 拒答复用既有 INVALID 契约：`_response` 的通用分支只要看到
            # answer_mode=INVALID 且 degraded=False，产出的字段就已经与 spec 一致
            # （analysis_sources=[NONE]、quality_status=NOT_RUN、quality_attempts=0），
            # 不需要为拒答单独写响应构造逻辑（design.md D7）。
            result["intent"] = QueryIntent(
                answer_mode=AnswerMode.INVALID, category=QuestionCategory.UNKNOWN
            )
            result["candidate_answer"] = _PREFILTER_REJECTION_MESSAGES[state["locale"]]
            # 只记分数、阈值与会话标识，不记问题原文或商家标识——运营靠这条日志
            # 发现误拒该调阈值还是补语料，不需要也不该看到问题内容（R4 日志脱敏约束）。
            logger.info(
                "问题范围闸门拒答",
                extra={
                    "prefilter_score": decision.score,
                    "prefilter_threshold": decision.threshold,
                    "session_id": str(state["session_id"]),
                },
            )
        return result

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
        locale = state["locale"]
        detail, queries = await self._retrieval.load_domain_with_cross_language_retrieval(
            initial.category,
            initial.intent_keywords,
            question=state["question"],
            locale=locale,
            budget=self._localization_budget,
        )
        notes = list(state["quality_notes"])
        if detail.has_incomplete:
            notes.append(
                _text(
                    "命中的知识资料尚未完整，回答仅基于现有内容",
                    "The matched knowledge material is incomplete; the answer is based "
                    "only on what is currently available.",
                    locale,
                )
            )
        if not detail.matched:
            notes.append(
                _text(
                    "未命中与当前问题相关的知识资料",
                    "No knowledge material relevant to this question was matched.",
                    locale,
                )
            )
        elif detail.source is KnowledgeSource.MEMORY_FALLBACK:
            notes.append(
                _text(
                    "团队知识库未命中，本次依据该商家的历史记忆作答",
                    "The team knowledge base had no match; this answer is based on this "
                    "merchant's historical memory instead.",
                    locale,
                )
            )
        # 口径检索放在正文层之后：三级检索的第三级要靠知识正文生成候选口径，
        # 而索引层只有目录词汇。节点顺序由计划 §10 固定，正文层在此才可用。
        metric: MetricPayload | None = None
        if intent.answer_mode is AnswerMode.METRIC:
            metric = (
                _generated_metric_payload(intent, locale)
                if intent.generated_metric_plan is not None
                else await self._catalog.resolve(intent, detail.text, state["budget"])
            )
        return {
            **self._step(state, "retrieve_knowledge_detail"),
            "knowledge_detail": detail,
            "metric_definition": metric,
            "quality_notes": notes,
            "retrieval_queries": queries,
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
        locale = state["locale"]
        if _is_table_only_detail(intent):
            # 参考实现要求纯明细正文必须为空。查询、表格、截断和导出仍由后续节点
            # 正常生成；这里不能塞进「已完成」之类的兜底文字，也不能调用回答模型。
            return {
                **self._step(state, "compose_answer"),
                "candidate_answer": "",
                "recommendations": [],
            }
        # `compose_answer` 排在 `query_data` 之后，所以这里能看到本轮到底查没查到
        # 数据。查到了还说「查询将在后续阶段接入」，就是一边给结果一边否认查询
        # 发生过——用户会连旁边的真实数字一起不信（AGENTS.md R7）。
        queried = state["query_result"] is not None
        answer = _text("已完成结构化理解。", "Structured understanding complete.", locale)
        if queried and intent.answer_mode in {AnswerMode.METRIC, AnswerMode.DETAIL}:
            facts = AnswerFacts(
                question=state["question"],
                metric=state["metric_definition"],
                query_result=_required(state["query_result"]),
            )
            if self._answer_llm is not None:
                return {
                    **self._step(state, "compose_answer"),
                    "answer_facts": facts,
                    "candidate_answer": "",
                    "recommendations": [],
                    "visualization": self._visualization_service.build(
                        facts.query_result,
                        facts.metric,
                    ),
                    "analysis_sources": [AnalysisSource.DATABASE],
                    "quality_status": QualityStatus.NOT_RUN,
                }
        if intent.answer_mode is AnswerMode.METRIC:
            answer = (
                _text(
                    "已按识别到的指标口径和时间范围查询经营数据，结果见下方数据与查询计划；"
                    "对数字的解读与图表将在后续阶段补齐。",
                    "Business data has been queried using the identified metric definition "
                    "and time range; see the data and query plan below. Interpretation and "
                    "charting will be added in a later stage.",
                    locale,
                )
                if queried
                # 降级分支说「尚未执行」是真话，保留；但不能承诺「将在某阶段接入」——
                # 受控查询本身已经交付了，这次没有数据是本次请求的问题，
                # 具体原因在 degraded_reason 里。
                else _text(
                    "已识别指标和查询范围，本次尚未执行经营数据查询。",
                    "The metric and query range have been identified, but no business "
                    "data query was executed this time.",
                    locale,
                )
            )
        elif intent.answer_mode is AnswerMode.DETAIL:
            answer = (
                _text(
                    "已按识别到的明细范围查询经营数据，结果见下方明细与查询计划；"
                    "对明细的解读与导出将在后续阶段补齐。",
                    "Business data has been queried using the identified detail range; "
                    "see the details and query plan below. Interpretation and export will "
                    "be added in a later stage.",
                    locale,
                )
                if queried
                else _text(
                    "已识别明细查询意图，本次尚未执行经营数据查询。",
                    "The detail query intent has been identified, but no business data "
                    "query was executed this time.",
                    locale,
                )
            )
        elif intent.answer_mode is AnswerMode.RULE:
            answer = _knowledge_answer(detail, locale)
        elif intent.answer_mode is AnswerMode.INVALID:
            answer = _text(
                "该请求包含不受支持或不安全的查询字段，无法执行。",
                "This request contains an unsupported or unsafe query field and cannot "
                "be executed.",
                locale,
            )
        return {**self._step(state, "compose_answer"), "candidate_answer": answer}

    async def _quality_loop(self, state: AgentState) -> dict[str, object]:
        facts = state["answer_facts"]
        if facts is None or self._answer_llm is None:
            return self._step(state, "quality_loop")
        outcome = await self._quality_loop_service.run(
            facts, self._answer_llm, self._reviewer_llm, state["budget"], locale=state["locale"]
        )
        return {
            **self._step(state, "quality_loop"),
            "candidate_answer": outcome.draft.answer,
            "recommendations": outcome.draft.recommendations,
            "quality_status": outcome.status,
            "attempt": outcome.attempts,
            "quality_notes": [*state["quality_notes"], *outcome.notes],
            "degraded": state["degraded"] or outcome.status is QualityStatus.DEGRADED,
            "degraded_reason": (
                _quality_degrade_reason(outcome.reason, state["locale"])
                if outcome.reason is not None
                else state["degraded_reason"]
            ),
        }

    async def _suggest_questions(self, state: AgentState) -> dict[str, object]:
        intent = _required(state["intent"])
        suggested = suggestions_for(intent.category, intent.answer_mode, state["locale"])
        current = suggested.current
        if self._history_questions is not None and self._merchant_id is not None:
            try:
                history = await self._history_questions.top_category_questions(
                    merchant_id=self._merchant_id,
                    category=intent.category.value,
                    limit=len(suggested.current) or 3,
                )
            except Exception:
                # 推荐问题不可用不影响已经生成的主回答。
                logger.warning("读取历史推荐问题失败，已回落到静态推荐", exc_info=True)
            else:
                if history:
                    # 商家历史高频问题是过去真实提问的原文快照（可能来自任一语言
                    # 的历史轮次），不是本模块能翻译的固定词条——按 Task 6 Step 6
                    # 的边界，这里不为它触发任何额外翻译调用，原样展示。
                    current = history
        return {
            **self._step(state, "suggest_questions"),
            "suggestions": current,
            "suggestion_alternates": suggested.alternates,
        }

    async def _persist_answer(self, state: AgentState) -> dict[str, object]:
        # 真实持久化由 ChatService 在商家范围与幂等保护内完成。
        return self._step(state, "persist_answer")

    def _response(self, state: AgentState) -> ChatResponse:
        intent = _required(state["intent"])
        locale = state["locale"]
        if intent.answer_mode is AnswerMode.METRIC:
            metric = state["metric_definition"] or _unverified_metric(intent.metric, locale)
            outcome = _query_outcome(
                state,
                fallback_query_plan=_text(
                    "已校验结构化查询意图，尚未执行数据查询。",
                    "The structured query intent has been validated, but no data query "
                    "was executed yet.",
                    locale,
                ),
                fallback_note=_text(
                    "当前未执行经营数据查询。", "No business data query was executed.", locale
                ),
                fallback_reason=_QUERY_SERVICE_UNAVAILABLE[locale],
            )
            notes = list(outcome.notes)
            if metric.generated and metric.notice is not None:
                # 生成口径必须带待核验说明，否则用户会把模型猜的口径当成正式口径。
                notes.append(metric.notice)
            visualization = state["visualization"]
            if visualization is None and state["query_result"] is not None:
                visualization = self._visualization_service.build(state["query_result"], metric)
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
                metric_sql_definition=metric.sql_definition,
                metric_dimensions=list(metric.dimensions),
                metric_source_database=metric.source_database,
                metric_source_table=metric.source_table,
                metric_report_url=metric.report_url,
                metric_source=metric.source,
                metric_generated=metric.generated,
                metric_notice=metric.notice,
                metric_owner=metric.owner,
                metric_status=MetricStatus(metric.status),
                data_rows=outcome.data_rows,
                total_rows=outcome.total_rows,
                truncated=outcome.truncated,
                visualization=visualization or Visualization(enabled=False),
                recommendations=state["recommendations"]
                or _metric_recommendations(outcome, metric, locale),
            )

        if intent.answer_mode is AnswerMode.DETAIL:
            export_id = uuid4()
            outcome = _query_outcome(
                state,
                fallback_query_plan=_text(
                    "已校验明细查询意图，尚未执行数据查询。",
                    "The detail query intent has been validated, but no data query was "
                    "executed yet.",
                    locale,
                ),
                fallback_note=_text(
                    "当前未执行经营明细查询。",
                    "No business detail query was executed.",
                    locale,
                ),
                fallback_reason=_QUERY_SERVICE_UNAVAILABLE[locale],
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
                recommendations=(
                    []
                    if _is_table_only_detail(intent)
                    else state["recommendations"] or _detail_recommendations(outcome, locale)
                ),
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
                quality_notes=[
                    *state["quality_notes"],
                    _text(
                        "当前未执行商家资料查询。",
                        "No merchant profile query was executed.",
                        locale,
                    ),
                ],
                analysis_sources=[AnalysisSource.FALLBACK],
                degraded=True,
                degraded_reason=_text(
                    "当前版本尚未开放商家资料查询",
                    "Merchant profile queries are not yet available in the current "
                    "version.",
                    locale,
                ),
                suggestions=state["suggestions"],
                suggestion_alternates=state["suggestion_alternates"],
                query_plan=QueryPlanSummary(
                    summary=_text(
                        "已校验身份资料查询意图，尚未执行数据查询。",
                        "The identity profile query intent has been validated, but no "
                        "data query was executed yet.",
                        locale,
                    )
                ),
                data_rows=[],
                total_rows=0,
                truncated=False,
            )
        knowledge_detail = state["knowledge_detail"]
        sources = (
            [
                AnalysisSource.MEMORY
                if knowledge_detail.source is KnowledgeSource.MEMORY_FALLBACK
                else AnalysisSource.KNOWLEDGE
            ]
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


def _is_table_only_detail(intent: QueryIntent) -> bool:
    """判断是否只展示 DETAIL 表格；模型布尔值不参与任何查询标识符选择。"""

    return intent.answer_mode is AnswerMode.DETAIL and not intent.analysis_requested


#: Task 5：写入 `degraded_reason` 单值字段的整句说明，与
#: `app.localization.catalog._GRAPH_DEGRADE_REASON_MESSAGES` 的词典 key 逐字
#: 一致——`DegradeReason -> 词表键` 这层映射本身已经是这个字典表达的结构，
#: 值改成通过 catalog 反查即可验证已登记，不需要另建一层间接。
#: 保持 `dict[DegradeReason, str]`（zh-CN 原句）这个形状不变：
#: `tests/unit/services/test_quality_loop.py::
#: test_graph_degrade_reason_messages_are_registered_in_the_bilingual_catalog`
#: 直接遍历 `.values()` 逐个喂给 `localize_catalog_value()`，改成嵌套 dict
#: 会让那条已有测试类型报错。
_DEGRADE_REASON_MESSAGES: Final[dict[DegradeReason, str]] = {
    DegradeReason.UPSTREAM: "回答生成或独立复核暂不可用，已返回受控数据摘要。",
    DegradeReason.BUDGET: "模型预算已达上限，已返回受控数据摘要。",
    DegradeReason.VALIDATION: "回答未通过质量校验，已返回受控数据摘要。",
}


def _quality_degrade_reason(reason: DegradeReason, locale: SupportedLocale) -> str:
    message = _DEGRADE_REASON_MESSAGES[reason]
    if locale is SupportedLocale.ZH_CN:
        return message
    # catalog 已登记这三句的英文译文（Task 5 §来源 graph.py 一节），
    # `localize_catalog_value()` 不命中时兜底原句而不是抛异常——宁可让极端
    # 情况下混入一句未翻译的中文，也不能让 degraded_reason 本身渲染失败。
    return localize_catalog_value(message, locale) or message


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


def _metric_recommendations(
    outcome: _QueryOutcome, metric: MetricPayload, locale: SupportedLocale
) -> list[Recommendation]:
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
                title=_text(
                    "本次没有取到经营数据", "No business data was retrieved this time", locale
                ),
                evidence=_text(
                    "已完成结构化意图校验，但尚未执行经营数据查询。",
                    "The structured intent has been validated, but no business data "
                    "query was executed.",
                    locale,
                ),
                action=_text(
                    "按上方降级说明调整问题后重试。",
                    "Adjust your question per the degradation notice above and try "
                    "again.",
                    locale,
                ),
            ),
            Recommendation(
                title=_text("核对指标口径", "Verify the metric definition", locale),
                evidence=_text(
                    f"已识别指标代码：{metric.metric_code}。",
                    f"Identified metric code: {metric.metric_code}.",
                    locale,
                ),
                action=_text(
                    "确认日期范围和维度后再查询。",
                    "Confirm the date range and dimensions before querying again.",
                    locale,
                ),
            ),
        ]
    return [
        Recommendation(
            title=_text("核对查询范围", "Verify the query scope", locale),
            evidence=_text(
                f"本次查询返回 {outcome.total_rows} 行数据。",
                f"This query returned {outcome.total_rows} rows.",
                locale,
            ),
            action=_text(
                "确认日期范围和维度是否覆盖你想了解的口径。",
                "Confirm whether the date range and dimensions cover what you want "
                "to know.",
                locale,
            ),
        ),
        Recommendation(
            title=_text("核对指标口径", "Verify the metric definition", locale),
            evidence=_text(
                f"已识别指标代码：{metric.metric_code}。",
                f"Identified metric code: {metric.metric_code}.",
                locale,
            ),
            action=_text(
                "如口径与预期不符，请调整问题后重新查询。",
                "If the definition does not match your expectation, adjust your "
                "question and query again.",
                locale,
            ),
        ),
    ]


def _detail_recommendations(
    outcome: _QueryOutcome, locale: SupportedLocale
) -> list[Recommendation]:
    """DETAIL 的 `recommendations`：同上，查到了就不能再说「尚未执行」。"""

    if not outcome.succeeded:
        return [
            Recommendation(
                title=_text(
                    "本次没有取到明细数据", "No detail data was retrieved this time", locale
                ),
                evidence=_text(
                    "已完成结构化意图校验，但尚未执行经营明细查询。",
                    "The structured intent has been validated, but no business detail "
                    "query was executed.",
                    locale,
                ),
                action=_text(
                    "按上方降级说明调整问题后重试。",
                    "Adjust your question per the degradation notice above and try "
                    "again.",
                    locale,
                ),
            ),
            Recommendation(
                title=_text("补充筛选条件", "Add more filter conditions", locale),
                evidence=_text(
                    "当前没有可展示的明细数据。",
                    "There is currently no detail data to display.",
                    locale,
                ),
                action=_text(
                    "补充日期或商品条件后再查询。",
                    "Add a date or product filter and query again.",
                    locale,
                ),
            ),
        ]
    scope_evidence = _text(
        (
            f"本次预览返回 {outcome.total_rows} 行，已达到预览上限，可能还有更多记录。"
            if outcome.truncated
            else f"本次预览返回 {outcome.total_rows} 行，已覆盖本次查询的全部结果。"
        ),
        (
            f"This preview returned {outcome.total_rows} rows and hit the preview "
            "limit; there may be more records."
            if outcome.truncated
            else f"This preview returned {outcome.total_rows} rows, covering the "
            "full result of this query."
        ),
        locale,
    )
    return [
        Recommendation(
            title=_text("核对查询范围", "Verify the query scope", locale),
            evidence=scope_evidence,
            action=_text(
                "确认筛选条件是否覆盖你想查看的记录。",
                "Confirm whether the filter conditions cover the records you want to "
                "see.",
                locale,
            ),
        ),
        Recommendation(
            title=_text("导出完整明细", "Export the full detail file", locale),
            evidence=_text(
                "预览行数受上限约束，导出可拿到完整明细文件。",
                "The preview row count is capped; use export to get the full detail "
                "file.",
                locale,
            ),
            action=_text(
                "如需完整明细用于外部处理，可使用导出功能。",
                "Use the export feature if you need the full detail file for "
                "external processing.",
                locale,
            ),
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


def _knowledge_answer(detail: KnowledgeResult | None, locale: SupportedLocale) -> str:
    """将受控检索结果写入规则回答，保留可核验的文档来源。

    `hit.content`（知识文档正文本身）刻意不在这里翻译——知识库内容的双语版本
    是 Task 8 的范围（人工可编辑的双版本文档），这里只负责翻译「壳」文案
    （引导语、来源标签、未命中提示），绝不改写或覆盖检索到的原文。
    """

    if detail is None or not detail.matched:
        return _text(
            "未命中与当前问题相关的知识资料，暂不能依据知识库给出规则结论。",
            "No knowledge material relevant to this question was matched; a "
            "rule-based conclusion cannot be given from the knowledge base yet.",
            locale,
        )

    hits = detail.hits
    source_label = _text("来源", "Source", locale)
    # Task 14 Step 7 finding B：标签本身（"来源"/"Source"）已经按 locale 选取，
    # 但分隔符过去硬编码成中文全角冒号「：」，en-US 请求会得到
    # "Source：xxx" 这种中英混杂的分隔符。分隔符与标签同源、同一 `_text()`
    # 选取方式，不额外发明新写法。
    source_separator = _text("：", ": ", locale)
    excerpts = [
        f"- {hit.content.strip()}\n  {source_label}{source_separator}{hit.source_path}"
        for hit in hits
        if hit.content.strip()
    ]
    if not excerpts:
        return _text(
            "未命中可展示正文的知识资料，暂不能依据知识库给出规则结论。",
            "No displayable knowledge material was matched; a rule-based "
            "conclusion cannot be given from the knowledge base yet.",
            locale,
        )
    intro = _text(
        "根据知识库检索到的资料：",
        "Based on material retrieved from the knowledge base:",
        locale,
    )
    return intro + "\n" + "\n".join(excerpts)


def _unverified_metric(metric_code: str | None, locale: SupportedLocale) -> MetricPayload:
    return MetricPayload(
        metric_code=metric_code or "unknown_metric",
        display_name=_text("待确认指标", "Metric pending confirmation", locale),
        unit="",
        definition=_text(
            "未命中正式指标目录，口径需人工确认后才能作为正式口径使用。",
            "This metric was not found in the official catalog; its definition "
            "requires manual confirmation before it can be treated as official.",
            locale,
        ),
        # `source` 不是最终展示文案：`MetricDefinitionSource._missing_()`
        # （见 `app.schemas.chat`）把这个固定中文标记兼容映射成
        # `METRIC_CATALOG` 协议枚举值，响应里只暴露枚举值本身（英文协议码），
        # 这句原文永远不会直接展示给用户，故不参与本地化。
        source="Borough 指标目录",
        owner=_text("经营分析组", "Business Analytics Team", locale),
        status=MetricStatus.UNVERIFIED.value,
        generated=False,
        notice=None,
        sql_definition="",
        dimensions=(),
        source_database="",
        source_table="",
    )


# 受控临时分组指标只支持这两个类别（由 whitelist.py 强制），用字典而非
# `"交易" if ... else "退款"` 的二选一三元表达式，未来若类别枚举出错会直接
# KeyError 而不是把未知类别静默归到「退款」。
_GENERATED_METRIC_CATEGORY_LABELS: Final[dict[str, dict[SupportedLocale, str]]] = {
    "TRADE": {SupportedLocale.ZH_CN: "交易", SupportedLocale.EN_US: "order"},
    "REFUND": {SupportedLocale.ZH_CN: "退款", SupportedLocale.EN_US: "refund"},
}
#: 上面用于组合成句（"按{category_label}明细..."）的单数形式；`definition`
#: 文案单独用复数形式更符合英文表达习惯，不复用同一份映射。
_GENERATED_METRIC_CATEGORY_LABELS_PLURAL_EN: Final[dict[str, str]] = {
    "TRADE": "orders",
    "REFUND": "refunds",
}
_GENERATED_METRIC_SOURCE_TABLES: Final[dict[str, str]] = {
    "TRADE": "orders",
    "REFUND": "refunds",
}


def _generated_metric_payload(intent: QueryIntent, locale: SupportedLocale) -> MetricPayload:
    """为受控临时分组指标生成可展示的、待核验的口径载荷。

    展示名称与单位来自已校验的结构化计划（`plan.name`/`plan.unit`）——它们是
    模型在回答提示词已被要求使用目标语言的前提下生成的自由文本，不在这里
    二次翻译；实际数值只来自 ``AnalyticsRepository.generated_metric`` 的
    交易/退款固定模板。
    """

    plan = intent.generated_metric_plan
    assert plan is not None
    category = intent.category
    category_label = _GENERATED_METRIC_CATEGORY_LABELS[category.value][locale]
    source_table = _GENERATED_METRIC_SOURCE_TABLES[category.value]
    dimensions = tuple(item for item in (plan.group_by, plan.filter_column) if item is not None)
    return MetricPayload(
        metric_code=f"generated_{category.value.lower()}_metric",
        display_name=plan.name,
        unit=plan.unit,
        definition=_text(
            f"按{category_label}明细的后端固定聚合模板计算。",
            "Computed by the backend's fixed aggregation template over "
            f"{_GENERATED_METRIC_CATEGORY_LABELS_PLURAL_EN[category.value]} details.",
            locale,
        ),
        source=MetricDefinitionSource.AI_GENERATED.value,
        owner=_text("待认领", "Unassigned", locale),
        status=MetricStatus.UNVERIFIED.value,
        generated=True,
        notice=_text(
            "展示名称和单位由模型提出，聚合口径已由后端固定模板执行，仍需人工确认。",
            "The display name and unit were proposed by the model; the aggregation "
            "was executed by the backend's fixed template and still requires manual "
            "confirmation.",
            locale,
        ),
        sql_definition=_text(
            "由后端受控聚合模板生成，不接受模型提供的 SQL 或公式。",
            "Generated by the backend's controlled aggregation template; no SQL or "
            "formula supplied by the model is accepted.",
            locale,
        ),
        dimensions=dimensions,
        source_database="public",
        source_table=source_table,
        report_url=None,
    )
