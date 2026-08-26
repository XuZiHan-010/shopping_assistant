"""拒答的可观测性日志（tasks.md 7.1；spec「判定行为必须可配置且可观测」）。"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest

from app.agent.graph import MerchantQaGraph
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricCatalog


class D:
    def __init__(self, p: str, title: str, c: str) -> None:
        self.source_path = p
        self.title = title
        self.content = c
        self.is_complete = True


class K:
    async def list_active(self) -> list[D]:
        return [D("index/README.md", "退款退货域", "退货 退款")]


class M:
    async def get_by_code(self, metric_code: str) -> None:
        return None


class _NoHistory:
    async def has_assistant_message(self, merchant_id: UUID, conversation_id: UUID) -> bool:
        del merchant_id, conversation_id
        return False


def _reenable_logger_disabled_by_alembic_file_config() -> None:
    """`migrations/env.py` 调用 `logging.config.fileConfig`（默认
    `disable_existing_loggers=True`），一旦同一进程内跑过 `tests/integration/
    test_migrations.py`，会把当时已存在的 `app.agent.graph` logger 全局置
    `disabled=True`，导致本文件的 caplog 断言在全量套件里变得跑序相关。
    这是测试基础设施的既有环境问题，与本次改动无关，这里只做防御性重置。
    """

    logging.getLogger("app.agent.graph").disabled = False


@pytest.mark.asyncio
async def test_rejection_logs_score_and_threshold(caplog: pytest.LogCaptureFixture) -> None:
    _reenable_logger_disabled_by_alembic_file_config()
    llm = FakeLlmClient(responses=[])
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        prefilter_enabled=True,
        prefilter_min_score=3,
        session_history=_NoHistory(),
        merchant_id=uuid4(),
    )

    with caplog.at_level(logging.INFO, logger="app.agent.graph"):
        await graph.run("CNN 和 RNN 的区别是什么", uuid4())

    records = [r for r in caplog.records if r.name == "app.agent.graph"]
    assert records, "拒答必须留下一条日志"
    record = records[0]
    assert record.prefilter_score == 0
    assert record.prefilter_threshold == 3


@pytest.mark.asyncio
async def test_rejection_log_does_not_contain_merchant_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """闸门日志只记录判定用的分数与阈值，不得把商家标识以外的隐私信息带进日志。"""

    _reenable_logger_disabled_by_alembic_file_config()
    llm = FakeLlmClient(responses=[])
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(K()),
        intent_service_llm=llm,
        catalog=MetricCatalog(M(), llm),
        prefilter_enabled=True,
        session_history=_NoHistory(),
        merchant_id=uuid4(),
    )

    with caplog.at_level(logging.INFO, logger="app.agent.graph"):
        await graph.run("CNN 和 RNN 的区别是什么", uuid4())

    matching = [r for r in caplog.records if r.name == "app.agent.graph"]
    assert matching, "拒答必须留下一条日志，否则下面的断言会无意义地通过"
    for record in matching:
        assert not hasattr(record, "question")
        assert not hasattr(record, "merchant_id")
