"""双知识库的硬优先级测试。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.knowledge.retrieval import KnowledgeRetrieval, KnowledgeSource
from app.schemas.chat import QuestionCategory


@dataclass
class _Doc:
    source_path: str
    title: str
    content: str
    is_complete: bool = True


@dataclass
class _Memory:
    category: str
    content: str


class _KnowledgeRepo:
    def __init__(self, documents: list[_Doc]) -> None:
        self._documents = documents

    async def list_active(self) -> list[_Doc]:
        return self._documents


class _MemoryRepo:
    def __init__(self, memories: list[_Memory]) -> None:
        self._memories = memories
        self.queried_merchants: list[UUID] = []

    async def list_for_merchant(self, merchant_id: UUID, category: str) -> list[_Memory]:
        self.queried_merchants.append(merchant_id)
        return [memory for memory in self._memories if memory.category == category]


def _trade_document() -> _Doc:
    return _Doc("业务/交易/业务流程/下单.md", "下单", "交易订单的下单流程说明")


@pytest.mark.asyncio
async def test_maintained_hit_excludes_memory_entirely() -> None:
    memory_repo = _MemoryRepo([_Memory("TRADE", "记忆内容不应出现")])
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([_trade_document()]), memories=memory_repo, merchant_id=uuid4()
    )

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    assert result.source is KnowledgeSource.MAINTAINED
    assert "记忆内容不应出现" not in result.text
    assert memory_repo.queried_merchants == []


@pytest.mark.asyncio
async def test_memory_is_used_only_when_maintained_is_empty() -> None:
    merchant_id = uuid4()
    memory_repo = _MemoryRepo([_Memory("TRADE", "去年双十一问过成交额")])
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([]), memories=memory_repo, merchant_id=merchant_id
    )

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    assert result.source is KnowledgeSource.MEMORY_FALLBACK
    assert "去年双十一问过成交额" in result.text
    assert result.matched is True
    assert memory_repo.queried_merchants == [merchant_id]


@pytest.mark.asyncio
async def test_source_marker_is_rendered_verbatim() -> None:
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([_trade_document()]), memories=_MemoryRepo([]), merchant_id=uuid4()
    )

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    assert result.text.startswith("[LLM_WIKI_SOURCE=maintained]")


@pytest.mark.asyncio
async def test_both_empty_reports_none() -> None:
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([]), memories=_MemoryRepo([]), merchant_id=uuid4()
    )

    result = await retrieval.load_domain(QuestionCategory.TRADE, ())

    assert result.source is KnowledgeSource.NONE
    assert result.matched is False
    assert result.text == ""


@pytest.mark.asyncio
async def test_memory_is_skipped_when_not_wired() -> None:
    result = await KnowledgeRetrieval(_KnowledgeRepo([])).load_domain(QuestionCategory.TRADE, ())

    assert result.source is KnowledgeSource.NONE


@pytest.mark.asyncio
async def test_index_layer_never_falls_back_to_memory() -> None:
    memory_repo = _MemoryRepo([_Memory("UNKNOWN", "记忆")])
    retrieval = KnowledgeRetrieval(_KnowledgeRepo([]), memories=memory_repo, merchant_id=uuid4())

    result = await retrieval.load_index()

    assert result.source is KnowledgeSource.NONE
    assert memory_repo.queried_merchants == []
