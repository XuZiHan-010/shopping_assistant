"""query_data 节点接入真实查询后的行为。

用假的查询服务：图这一层要验证的是「拿到结果怎么填响应」，SQL 正确性由
tests/integration 的仓储测试负责。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.agent.graph import MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog
from app.repositories.analytics import ResultColumn
from app.schemas.chat import AnalysisSource, AnswerMode, ChatResponse, QualityStatus
from app.services.safe_query import QueryResult, UnsupportedQueryError


class _Documents:
    async def list_active(self) -> list[object]:
        return []


class _NoMetric:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _StubQueryService:
    def __init__(self, result: QueryResult | Exception) -> None:
        self._result = result
        self.calls = 0
        #: `_query_data` 现在总是显式传 `keywords`（REFUND 类别的退款/退货
        #: 二次路由要用），这里记录下来供路由测试断言它被正确透传。
        self.received_keywords: Sequence[str] | None = None

    async def execute(
        self,
        context: object,
        intent: object,
        *,
        now: object,
        keywords: Sequence[str] = (),
    ) -> QueryResult:
        self.calls += 1
        self.received_keywords = keywords
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _metric_result() -> QueryResult:
    return QueryResult(
        columns=(
            ResultColumn("date", "日期", "DIMENSION"),
            ResultColumn("gmv", "成交 GMV", "METRIC"),
        ),
        rows=[{"date": date(2026, 8, 3), "gmv": Decimal("1200.00")}],
        total_rows=1,
        truncated=False,
        source_tables=("orders",),
        plan_steps=("按商家范围检索成交 GMV",),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


def _llm() -> FakeLlmClient:
    return FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            json.dumps(
                {
                    "answer_mode": "METRIC",
                    "category": "TRADE",
                    "metric": "gmv",
                    "dimensions": ["date"],
                    "filters": {},
                    "date_range": {"start": "2026-08-03", "end": "2026-08-03"},
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                }
            ),
        ]
    )


def _graph(service: _StubQueryService) -> MerchantQaGraph:
    llm = _llm()
    return MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
        query_service=service,
        merchant_id=uuid4(),
    )


def _detail_result() -> QueryResult:
    return QueryResult(
        columns=(ResultColumn("order_no", "订单号", "DIMENSION"),),
        rows=[{"order_no": "BR20260803-0001"}],
        total_rows=1,
        truncated=False,
        source_tables=("orders",),
        plan_steps=("按商家范围检索订单明细",),
        export_spec=None,
        notes=(),
        non_additive=False,
    )


def _llm_detail(*, analysis_requested: bool = True) -> FakeLlmClient:
    return FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "DETAIL", "category": "TRADE", "intent_keywords": ["订单"]}),
            json.dumps(
                {
                    "answer_mode": "DETAIL",
                    "category": "TRADE",
                    "metric": None,
                    "dimensions": [],
                    "filters": {},
                    "date_range": {"start": "2026-08-03", "end": "2026-08-03"},
                    "sort": None,
                    "limit": None,
                    "followup_reference": False,
                    "needs_attachment": False,
                    "analysis_requested": analysis_requested,
                }
            ),
        ]
    )


def _detail_graph(
    service: _StubQueryService, *, analysis_requested: bool = True
) -> MerchantQaGraph:
    llm = _llm_detail(analysis_requested=analysis_requested)
    return MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
        query_service=service,
        merchant_id=uuid4(),
    )


#: 有真实数据却在响应里说「查询没发生」，比没写文案更糟——
#: 那是让用户不信任真实数字的不诚实（AGENTS.md R7）。指向阶段代号的
#: 「将在 X 接入」由 `test_stage_reference_hygiene.py` 单独机械拦截。
_DENIAL_PHRASES = ("尚未执行", "未执行经营", "没有取到")


@pytest.mark.asyncio
async def test_metric_answer_carries_real_rows_and_drops_the_b4_fallback() -> None:
    service = _StubQueryService(_metric_result())

    result = await _graph(service).run("昨天 GMV", uuid4())

    assert service.calls == 1
    assert result.response.data_rows == [{"date": "2026-08-03", "gmv": "1200.00"}]
    assert result.response.total_rows == 1
    assert result.response.analysis_sources == [AnalysisSource.DATABASE]
    assert result.response.degraded is False


@pytest.mark.asyncio
async def test_query_data_passes_the_classification_keywords_through() -> None:
    """`SafeQueryService` 的 REFUND 退款/退货二次路由靠这些关键词判断；

    `_query_data` 必须把分类阶段（`classify_intent`）产出的
    `initial_intent.intent_keywords` 原样透传，不能悄悄丢在图里。
    """

    service = _StubQueryService(_metric_result())

    await _graph(service).run("昨天 GMV", uuid4())

    assert service.received_keywords == ("GMV",)


@pytest.mark.asyncio
async def test_query_plan_summary_comes_from_the_query_not_a_placeholder() -> None:
    service = _StubQueryService(_metric_result())

    result = await _graph(service).run("昨天 GMV", uuid4())

    assert result.response.query_plan is not None
    assert "成交 GMV" in result.response.query_plan.summary


@pytest.mark.asyncio
async def test_refused_query_degrades_visibly_instead_of_faking_data() -> None:
    """查询被拒时绝不能返回空数组假装「没有数据」。"""

    service = _StubQueryService(UnsupportedQueryError("指标 seller_secret 不在可查询范围内"))

    result = await _graph(service).run("查个不存在的指标", uuid4())

    assert result.response.degraded is True
    assert "不在可查询范围内" in (result.response.degraded_reason or "")
    assert result.response.analysis_sources == [AnalysisSource.FALLBACK]
    assert result.response.quality_status is QualityStatus.DEGRADED


@pytest.mark.asyncio
async def test_no_query_service_keeps_the_previous_degradation_path() -> None:
    """未注入查询服务（例如单测环境）时，行为退回 B3 的可见降级，而不是崩溃。"""

    llm = _llm()
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_Documents()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetric(), llm),
    )

    result = await graph.run("昨天 GMV", uuid4())

    assert result.response.answer_mode is AnswerMode.METRIC
    assert result.response.degraded is True


def _assert_no_denial(response: ChatResponse) -> None:
    """自洽性不变量作用在**整个响应**上，不是某一个字段上。

    上一轮只扫 `recommendations`，于是同一条响应里 `answer` 说「查询将在 B4
    接入」、`data_rows` 却带着真实数字，测试照样通过。字段作用域的不变量挡不住
    相邻字段——所以这里穷举所有会被用户读到的自然语言字段。
    """

    recommendations = response.recommendations or []
    assert recommendations
    texts: list[tuple[str, str]] = [("answer", response.answer)]
    texts.extend(
        (
            "recommendations",
            f"{recommendation.title}{recommendation.evidence}{recommendation.action}",
        )
        for recommendation in recommendations
    )
    texts.extend(("quality_notes", note) for note in response.quality_notes)
    texts.append(("degraded_reason", response.degraded_reason or ""))
    for field, text in texts:
        for phrase in _DENIAL_PHRASES:
            assert phrase not in text, f"{phrase!r} 出现在成功查询的 {field} 里：{text!r}"


@pytest.mark.asyncio
async def test_successful_metric_response_never_denies_the_query_happened() -> None:
    """查到数据后，响应的任何一个字段都不能还说「尚未执行」。"""

    service = _StubQueryService(_metric_result())

    result = await _graph(service).run("昨天 GMV", uuid4())

    assert result.response.degraded is False
    assert result.response.data_rows
    _assert_no_denial(result.response)


@pytest.mark.asyncio
async def test_successful_detail_response_never_denies_the_query_happened() -> None:
    service = _StubQueryService(_detail_result())

    result = await _detail_graph(service).run("查看最近订单明细", uuid4())

    assert result.response.degraded is False
    assert result.response.data_rows
    _assert_no_denial(result.response)


@pytest.mark.asyncio
async def test_table_only_detail_returns_the_same_query_result_without_analysis() -> None:
    """只要求查看时，查询仍受同一白名单保护，但响应不应附带分析正文。"""

    service = _StubQueryService(_detail_result())

    result = await _detail_graph(service, analysis_requested=False).run("查看最近订单明细", uuid4())

    assert service.calls == 1
    assert result.response.data_rows == [{"order_no": "BR20260803-0001"}]
    assert result.response.total_rows == 1
    assert result.response.answer == ""
    assert result.response.recommendations == []


@pytest.mark.asyncio
async def test_successful_metric_answer_states_the_query_ran() -> None:
    """`answer` 是用户最先读到的字段，必须如实说查询已经执行过。

    只断言「不含否认文案」不够——一个空字符串也能通过；这里同时钉住它确实
    在讲本次查询。
    """

    service = _StubQueryService(_metric_result())

    result = await _graph(service).run("昨天 GMV", uuid4())

    assert "已按" in result.response.answer
    assert "查询" in result.response.answer


@pytest.mark.asyncio
async def test_degraded_metric_answer_keeps_the_not_executed_wording() -> None:
    """没有查询结果时说「尚未执行」是真话，不能因为上面的修复被一并抹掉——
    否则降级会变得对用户不可见（AGENTS.md R7）。
    """

    service = _StubQueryService(UnsupportedQueryError("指标 seller_secret 不在可查询范围内"))

    result = await _graph(service).run("查个不存在的指标", uuid4())

    assert result.response.degraded is True
    assert "尚未执行" in result.response.answer
