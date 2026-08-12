"""MerchantQaGraph 配置 node_timer 时记录每个节点耗时。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.agent.graph import GRAPH_NODES, MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog


class _Document:
    def __init__(self, path: str, content: str) -> None:
        self.source_path = path
        self.title = path
        self.content = content
        self.is_complete = True


class _KnowledgeRepo:
    async def list_active(self) -> list[_Document]:
        return [_Document("index/README.md", "交易"), _Document("业务/交易/正文.md", "订单 GMV")]


class _MetricRepo:
    async def get_by_code(self, metric_code: str) -> None:
        return None


@dataclass
class FakeNodeTimer:
    recorded: list[tuple[str, float]] = field(default_factory=list)

    def record_node_duration(self, node: str, duration_seconds: float) -> None:
        self.recorded.append((node, duration_seconds))


def _metric_response() -> str:
    return json.dumps(
        {
            "answer_mode": "METRIC",
            "category": "TRADE",
            "metric": "gmv",
            "dimensions": [],
            "filters": {},
            "date_range": None,
            "sort": None,
            "limit": None,
            "followup_reference": False,
            "needs_attachment": False,
        }
    )


def _graph(*, timer: FakeNodeTimer | None = None) -> MerchantQaGraph:
    llm = FakeLlmClient(
        responses=[
            json.dumps({"answer_mode": "METRIC", "category": "TRADE", "intent_keywords": ["GMV"]}),
            _metric_response(),
        ]
    )
    return MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_KnowledgeRepo()),
        intent_service_llm=llm,
        catalog=MetricCatalog(_MetricRepo(), llm),
        node_timer=timer,
    )


@pytest.mark.asyncio
async def test_all_graph_nodes_report_duration_when_timer_configured() -> None:
    timer = FakeNodeTimer()
    await _graph(timer=timer).run("昨天GMV", uuid4())
    assert [node for node, _duration in timer.recorded] == list(GRAPH_NODES)
    assert all(duration >= 0 for _node, duration in timer.recorded)


@pytest.mark.asyncio
async def test_graph_runs_normally_without_node_timer() -> None:
    result = await _graph().run("昨天GMV", uuid4())
    assert [step.node for step in result.steps] == list(GRAPH_NODES)
