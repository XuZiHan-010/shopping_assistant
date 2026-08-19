"""指标口径三级检索行为。"""

from __future__ import annotations

import json

import pytest

from app.intent.models import QueryIntent
from app.llm.client import STRUCTURED_CALL_OPTIONS, LlmBudget
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import GENERATED_NOTICE, MetricCatalog
from app.metrics.field_comments import FIELD_COMMENT_DEFINITIONS
from app.schemas.chat import AnswerMode, QuestionCategory


class _FakeMetricRow:
    def __init__(self, metric_code: str) -> None:
        self.metric_code = metric_code
        self.display_name = "支付成交额"
        self.unit = "元"
        self.business_definition = "统计口径说明"
        self.sql_definition = "SUM(gmv)"
        self.source = "Borough 指标目录"
        self.owner = "经营分析组"
        self.status = "ACTIVE"


class _FakeMetricRepository:
    def __init__(self, rows: dict[str, _FakeMetricRow]) -> None:
        self._rows = rows

    async def get_by_code(self, metric_code: str) -> _FakeMetricRow | None:
        return self._rows.get(metric_code)


def _intent(metric: str | None) -> QueryIntent:
    return QueryIntent(
        answer_mode=AnswerMode.METRIC, category=QuestionCategory.TRADE, metric=metric
    )


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=3, max_tokens=1_000)


@pytest.mark.asyncio
async def test_official_metric_does_not_call_the_llm() -> None:
    """正式指标命中却调用模型会无谓消耗成本并降低确定性。"""

    llm = FakeLlmClient(responses=["不该被用到"])
    catalog = MetricCatalog(_FakeMetricRepository({"gmv": _FakeMetricRow("gmv")}), llm)

    payload = await catalog.resolve(_intent("gmv"), "", _budget())

    assert payload is not None
    assert payload.generated is False
    assert payload.status == "ACTIVE"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_generated_metric_is_explicitly_unverified() -> None:
    """生成口径若未标注待核验，会被用户误当正式指标。"""

    generated = json.dumps(
        {"display_name": "临时口径", "unit": "单", "definition": "由模型生成"}, ensure_ascii=False
    )
    llm = FakeLlmClient(responses=[generated])
    catalog = MetricCatalog(_FakeMetricRepository({}), llm)

    payload = await catalog.resolve(_intent("unknown_metric_1d"), "知识正文", _budget())

    assert payload is not None
    assert payload.generated is True
    assert payload.status == "UNVERIFIED"
    assert payload.source == "AI_GENERATED"
    assert payload.notice == GENERATED_NOTICE
    assert "yshopping" not in payload.notice.lower()
    assert llm.call_options == [STRUCTURED_CALL_OPTIONS]


@pytest.mark.asyncio
async def test_field_comment_is_used_before_llm() -> None:
    """目录缺失时，二级字段注释优先于模型候选，且不消耗模型调用。"""

    llm = FakeLlmClient(responses=["不应调用"])
    payload = await MetricCatalog(_FakeMetricRepository({}), llm).resolve(
        _intent("gmv"), "", _budget()
    )

    assert payload is not None
    assert payload.source == "FIELD_COMMENT"
    assert payload.generated is False
    assert payload.display_name == "成交 GMV"
    assert payload.unit == "元"
    assert payload.source_table == "orders"
    assert payload.dimensions == FIELD_COMMENT_DEFINITIONS["gmv"].dimensions
    assert llm.calls == []


@pytest.mark.asyncio
async def test_non_metric_intents_do_not_resolve_a_definition() -> None:
    """闲聊解析口径会给非分析回答附加错误的指标面板。"""

    catalog = MetricCatalog(_FakeMetricRepository({}), FakeLlmClient())

    payload = await catalog.resolve(
        QueryIntent(answer_mode=AnswerMode.CHAT, category=QuestionCategory.UNKNOWN), "", _budget()
    )

    assert payload is None


@pytest.mark.asyncio
async def test_invalid_llm_json_does_not_emit_a_metric_payload() -> None:
    """模型返回非法 JSON 时，指标面板必须安全地缺席而非崩溃。"""

    catalog = MetricCatalog(_FakeMetricRepository({}), FakeLlmClient(behaviour="invalid_json"))

    assert await catalog.resolve(_intent("unknown_metric_1d"), "", _budget()) is None


@pytest.mark.asyncio
async def test_empty_llm_content_does_not_emit_a_metric_payload() -> None:
    """空正文与非法 JSON 一样不能成为临时指标口径。"""

    catalog = MetricCatalog(_FakeMetricRepository({}), FakeLlmClient(responses=[""]))

    assert await catalog.resolve(_intent("unknown_metric_1d"), "", _budget()) is None


@pytest.mark.asyncio
async def test_generated_metric_prompt_carries_a_full_json_example() -> None:
    """只报字段名不给形状，模型就会自造嵌套结构（2026-08-17 的 understand 事故同因）。"""

    from app.metrics.catalog import METRIC_CATALOG_EXAMPLE

    llm = FakeLlmClient(responses=[METRIC_CATALOG_EXAMPLE])
    catalog = MetricCatalog(_FakeMetricRepository({}), llm)

    payload = await catalog.resolve(_intent("unknown_metric_1d"), "知识正文", _budget())

    assert METRIC_CATALOG_EXAMPLE in llm.calls[0][1]
    assert payload is not None
    assert payload.display_name == "退货量"
