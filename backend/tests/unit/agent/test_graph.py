from __future__ import annotations

import json
import re
from uuid import uuid4

import pytest

from app.agent.graph import GRAPH_NODES, MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale
from app.metrics.catalog import MetricCatalog
from app.repositories.analytics import ResultColumn
from app.schemas.chat import AnalysisSource, AnswerMode, QualityStatus
from app.services.safe_query import QueryResult

_HAN = re.compile("[一-鿿]")


def _collect_visible_strings(value: object) -> list[str]:
    """递归收集 ChatResponse 里所有字符串叶子节点，供中文残留断言使用。"""

    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(_collect_visible_strings(item))
    elif isinstance(value, list | tuple):
        for item in value:
            found.extend(_collect_visible_strings(item))
    return found


class D:
    def __init__(self, p: str, c: str) -> None:
        self.source_path = p
        self.title = p
        self.content = c
        self.is_complete = True


class K:
    def __init__(self, documents: list[D] | None = None) -> None:
        self._documents = documents or [
            D("index/README.md", "交易"),
            D("业务/交易/正文.md", "订单 GMV"),
        ]

    async def list_active(self) -> list[D]:
        return self._documents


class EmptyK:
    async def list_active(self) -> list[D]:
        return []


class M:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class Memory:
    def __init__(self, category: str, content: str) -> None:
        self.category = category
        self.content = content


class MemoryRepo:
    def __init__(self, memories: list[Memory]) -> None:
        self._memories = memories

    async def list_for_merchant(self, merchant_id, category: str) -> list[Memory]:
        del merchant_id
        return [memory for memory in self._memories if memory.category == category]


def response(mode: str, metric: str | None) -> str:
    return json.dumps(
        {
            "answer_mode": mode,
            "category": "TRADE" if mode == "METRIC" else "UNKNOWN",
            "metric": metric,
            "dimensions": [],
            "filters": {},
            "date_range": None,
            "sort": None,
            "limit": None,
            "followup_reference": False,
            "needs_attachment": False,
        }
    )


@pytest.mark.asyncio
async def test_graph_emits_all_nodes_and_routes_metric() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            response("METRIC", "gmv"),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )
    result = await graph.run("昨天GMV", uuid4())
    assert result.response.answer_mode is AnswerMode.METRIC
    assert [step.node for step in result.steps] == list(GRAPH_NODES)


def rule_response() -> str:
    return json.dumps(
        {
            "answer_mode": "RULE",
            "category": "PLATFORM_RULE",
            "metric": None,
            "dimensions": [],
            "filters": {},
            "date_range": None,
            "sort": None,
            "limit": None,
            "followup_reference": False,
            "needs_attachment": False,
        }
    )


@pytest.mark.asyncio
async def test_graph_rule_answer_uses_knowledge_content_and_source() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {
                    "answer_mode": "RULE",
                    "category": "PLATFORM_RULE",
                    "intent_keywords": ["上架"],
                }
            ),
            rule_response(),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K([D("rules/listing.md", "商品上架前必须完成资质审核。")])),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
    )

    result = await graph.run("商品上架有什么规则", uuid4())

    assert "商品上架前必须完成资质审核" in result.response.answer
    assert "rules/listing.md" in result.response.answer
    assert result.response.analysis_sources == [AnalysisSource.KNOWLEDGE]


@pytest.mark.asyncio
async def test_graph_rule_answer_surfaces_memory_not_team_knowledge() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {
                    "answer_mode": "RULE",
                    "category": "PLATFORM_RULE",
                    "intent_keywords": ["上架"],
                }
            ),
            rule_response(),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(
            EmptyK(),
            memories=MemoryRepo([Memory("PLATFORM_RULE", "历史规则记忆")]),
            merchant_id=uuid4(),
        ),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
    )

    result = await graph.run("商品上架有什么规则", uuid4())

    assert result.response.analysis_sources == [AnalysisSource.MEMORY]
    assert any("历史记忆" in note for note in result.response.quality_notes)


@pytest.mark.asyncio
async def test_graph_rule_answer_explicitly_reports_knowledge_miss() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {
                    "answer_mode": "RULE",
                    "category": "PLATFORM_RULE",
                    "intent_keywords": ["入库"],
                }
            ),
            rule_response(),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K([D("index/README.md", "交易目录")])),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
    )

    result = await graph.run("入库流程是什么", uuid4())

    assert "未命中" in result.response.answer
    assert any("未命中" in note for note in result.response.quality_notes)
    assert result.response.analysis_sources == [AnalysisSource.NONE]


@pytest.mark.asyncio
async def test_graph_marks_budget_exhaustion_as_visible_chat_degradation() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "CHAT", "category": "UNKNOWN", "intent_keywords": []})
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        max_llm_calls=1,
    )

    result = await graph.run("你好", uuid4())

    assert result.response.answer_mode is AnswerMode.CHAT
    assert result.response.degraded is True
    assert "调用次数或 token" in (result.response.degraded_reason or "")
    assert result.response.quality_status is QualityStatus.DEGRADED
    assert result.response.analysis_sources == [AnalysisSource.FALLBACK]


@pytest.mark.asyncio
async def test_graph_marks_unconfigured_llm_as_visible_chat_degradation() -> None:
    llm = FakeLlmClient(configured=False)
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("你好", uuid4())

    assert result.response.answer_mode is AnswerMode.CHAT
    assert result.response.degraded is True
    assert "未配置" in (result.response.degraded_reason or "")
    assert result.response.quality_status is QualityStatus.DEGRADED


@pytest.mark.asyncio
async def test_graph_routes_detail_to_visible_b4_degradation() -> None:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "DETAIL", "category": "TRADE", "intent_keywords": ["订单"]}),
            response("DETAIL", None),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("查看最近订单明细", uuid4())

    assert result.response.answer_mode is AnswerMode.DETAIL
    assert result.response.degraded is True
    assert result.response.data_rows == []
    assert result.response.export is not None


class _RecordingLlm:
    """记录每次调用的 user prompt，用来断言口径检索拿到的是哪一层知识。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def is_configured(self) -> bool:
        return True

    async def complete(
        self, *, system: str, user: str, fallback: str, budget: object, options: object = None
    ) -> object:
        from app.llm.client import LlmResult

        del options
        self.prompts.append(user)
        return LlmResult(
            self._responses.pop(0) if self._responses else fallback,
            10,
            False,
            usage_known=True,
        )


@pytest.mark.asyncio
async def test_generated_metric_definition_is_built_from_the_domain_body(monkeypatch) -> None:
    """索引层只有目录词汇；用它生成口径等于让模型凭空编。"""

    monkeypatch.setattr("app.metrics.catalog.find_field_comment", lambda _code: None)
    llm = _RecordingLlm(
        [
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            response("METRIC", "gmv"),
            json.dumps(
                {"display_name": "成交 GMV", "unit": "元", "definition": "已支付订单金额。"}
            ),
        ]
    )
    documents = [
        D("index/README.md", "交易 目录"),
        D("业务/交易/业务名词解释/GMV.md", "GMV 指已支付订单金额之和。"),
    ]
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K(documents)),
        intent_service_llm=llm,  # type: ignore[arg-type]
        catalog=MetricCatalog(M(), llm),  # type: ignore[arg-type]
    )

    await graph.run("昨天 GMV", uuid4())

    assert "GMV 指已支付订单金额之和。" in llm.prompts[-1]


@pytest.mark.asyncio
async def test_generated_metric_definition_carries_the_pending_review_notice(monkeypatch) -> None:
    """生成口径不标注待核验，用户会把模型猜的口径当成正式口径。"""

    monkeypatch.setattr("app.metrics.catalog.find_field_comment", lambda _code: None)
    from app.metrics.catalog import GENERATED_NOTICE

    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            response("METRIC", "gmv"),
            json.dumps(
                {"display_name": "成交 GMV", "unit": "元", "definition": "已支付订单金额。"}
            ),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("昨天 GMV", uuid4())

    assert result.response.metric_status.value == "UNVERIFIED"
    assert any(GENERATED_NOTICE in note for note in result.response.quality_notes)


@pytest.mark.asyncio
async def test_backend_date_clamp_is_reported_to_the_user() -> None:
    """后端悄悄改窄区间而不说明，用户会以为看到的是自己问的那段时间。"""

    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": "TRADE",
                    "metric": "gmv",
                    "dimensions": [],
                    "filters": {},
                    "date_range": {"start": "2020-01-01", "end": "2020-12-31"},
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("2020 年 GMV", uuid4())

    assert any("日期" in note for note in result.response.quality_notes)


# --- Task 6：locale 贯穿问答图 ----------------------------------------------


@pytest.mark.asyncio
async def test_english_locale_produces_a_response_with_no_han_characters() -> None:
    """Task 6 Step 1 的图层等价验证：`locale=en-US` 时整份 `ChatResponse`
    （技术字段除外）不应含任何汉字——不需要真实数据库或真实 LLM，直接对
    `MerchantQaGraph.run(..., locale=...)` 的产出做递归扫描。

    HTTP 层的端到端等价测试（brief Step 1 原文示例）见
    `tests/api/test_chat.py::test_english_chat_localizes_every_visible_field`，
    因为需要真实 PostgreSQL 落库整轮会话/回答，在本地无 Docker 环境下只能
    跳过；这里在图这一层直接验证同一件事，不依赖数据库。
    """

    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "CHAT", "category": "UNKNOWN", "intent_keywords": []}),
            json.dumps(
                {
                    "answer_mode": "CHAT",
                    "category": "UNKNOWN",
                    "metric": None,
                    "dimensions": [],
                    "filters": {},
                    "date_range": None,
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("Hello there", uuid4(), locale=SupportedLocale.EN_US)

    assert result.response.answer_mode is AnswerMode.CHAT
    assert result.response.answer == "Structured understanding complete."
    assert [step.label for step in result.steps] == [
        "Identifying merchant and conversation context",
        "Loading the business knowledge index",
        "Determining question scope",
        "Classifying question type and business domain",
        "Structuring the question intent",
        "Validating the query intent",
        "Loading business knowledge details",
        "Querying business data",
        "Composing the answer",
        "Validating and reviewing answer quality",
        "Generating suggested questions",
        "Saving this answer",
    ]
    payload = result.response.model_dump(mode="json")
    # 技术字段（id、UUID、协议枚举值、node 内部标识）不受本条断言约束；
    # 白名单只保留真正会出现汉字的人类可读字段范围一致地扫描整份 payload。
    visible = _collect_visible_strings(payload)
    offending = [text for text in visible if _HAN.search(text)]
    assert offending == [], f"英文响应混入了汉字：{offending!r}"


@pytest.mark.asyncio
async def test_default_locale_is_chinese_and_unaffected_by_task_6() -> None:
    """默认（未显式传 locale）行为必须还是中文——不能因为新增了 locale 参数
    就意外改变了所有既有零参数调用点的既有语言。"""

    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "CHAT", "category": "UNKNOWN", "intent_keywords": []}),
            json.dumps(
                {
                    "answer_mode": "CHAT",
                    "category": "UNKNOWN",
                    "metric": None,
                    "dimensions": [],
                    "filters": {},
                    "date_range": None,
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()), intent_service_llm=llm, catalog=MetricCatalog(M(), llm)
    )

    result = await graph.run("你好", uuid4())

    assert result.response.answer == "已完成结构化理解。"
    assert result.steps[0].label == "识别商家与会话上下文"


class _FakeQueryService:
    """让 METRIC 分支真正 `queried=True`，从而真正跑到 `_quality_loop` 节点
    （而不是 CHAT 短路：`facts is None` 时 `_quality_loop` 直接跳过）。"""

    async def execute(self, context: object, intent: object, *, now: object, keywords=()):
        del context, intent, now, keywords
        return QueryResult(
            columns=(ResultColumn("refund_amount", "退款金额", "METRIC"),),
            rows=[{"refund_amount": 500}],
            total_rows=1,
            truncated=False,
            source_tables=("refunds",),
            plan_steps=("scan refunds",),
            export_spec=None,
            notes=(),
            non_additive=False,
        )


@pytest.mark.asyncio
async def test_english_locale_localizes_a_real_answer_validation_failure() -> None:
    """回归测试（code review 发现的 Important 缺口）：`quality_loop.py` 里
    `_MSG_EMPTY_MODEL_OUTPUT`/`_MSG_UNPARSEABLE_JSON` 曾经漏接
    `_localized()`，`answer_service.py::_validate()` 曾经完全不接受
    `locale` 参数——都不会被"零 Han 残留"测试捕获，因为那些测试走的是
    CHAT/degraded 快速路径（`facts is None` 时 `_quality_loop` 直接
    `return self._step(state, "quality_loop")`，根本不会调用
    `QualityLoop.run()`）。

    这里真正让 METRIC 分支查询成功（`_FakeQueryService`），逼真实的
    `_quality_loop` → `AnswerService._validate()` 跑起来：模型第一次起草的
    回答里混入一个内部 UUID，`_validate()` 会产出一条真实校验失败
    （不是 JSON 解析失败），必须能在 `en-US` 请求下正确本地化，不能在
    `quality_notes` 里混入中文。
    """

    llm = FakeLlmClient(
        responses=[
            json.dumps(
                {"answer_mode": "METRIC", "category": "REFUND", "intent_keywords": ["refund"]}
            ),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": "REFUND",
                    "metric": "refund_amount",
                    "dimensions": [],
                    "filters": {},
                    "date_range": None,
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
            # 起草：混入一个内部 UUID——`AnswerService._validate()` 的
            # `_UUID` 检查会真实触发，产出一条本地校验 issue（不是模型输出
            # 为空/无法解析这种上游失败）。
            json.dumps(
                {
                    "answer": (
                        "Refund order 123e4567-e89b-12d3-a456-426614174000 "
                        "totalled 500 CNY."
                    ),
                    "recommendations": [
                        {
                            "title": "Verify query scope",
                            "evidence": "This query returned 1 row.",
                            "action": "Confirm the date range covers what you need.",
                        },
                        {
                            "title": "Verify metric definition",
                            "evidence": "Identified metric code: refund_amount.",
                            "action": "Adjust the question if the definition is unexpected.",
                        },
                    ],
                }
            ),
        ]
    )
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        query_service=_FakeQueryService(),
        merchant_id=uuid4(),
        answer_llm=llm,
        reviewer_llm=llm,
        # 只给一轮机会：起草失败校验后直接落 DEGRADED，不需要为重试再排更多
        # FakeLlmClient 响应——`_MSG_MAX_RETRIES_REACHED` 本身已经是既有测试
        # 覆盖过的路径，这里只关心"这一轮的校验 issue 有没有被正确本地化"。
        quality_max_attempts=1,
    )

    result = await graph.run(
        "Refund amount in the last 7 days", uuid4(), locale=SupportedLocale.EN_US
    )

    assert result.response.answer_mode is AnswerMode.METRIC
    assert result.response.quality_status is QualityStatus.DEGRADED
    # 真正命中了本地校验 issue（不是走空转/无关分支）：英文译文必须出现。
    notes_text = " ".join(result.response.quality_notes)
    assert "internal identifier" in notes_text
    offending = [note for note in result.response.quality_notes if _HAN.search(note)]
    assert offending == [], f"quality_notes 混入了汉字：{offending!r}"
