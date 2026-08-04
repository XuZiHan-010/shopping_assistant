"""指标口径三级检索行为。"""

from __future__ import annotations

import json

import pytest

from app.intent.models import QueryIntent
from app.llm.client import LlmBudget
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import GENERATED_NOTICE, MetricCatalog
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
    catalog = MetricCatalog(_FakeMetricRepository({}), FakeLlmClient(responses=[generated]))

    payload = await catalog.resolve(_intent("unknown_metric_1d"), "知识正文", _budget())

    assert payload is not None
    assert payload.generated is True
    assert payload.status == "UNVERIFIED"
    assert payload.notice == GENERATED_NOTICE
    assert "yshopping" not in payload.notice.lower()


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
