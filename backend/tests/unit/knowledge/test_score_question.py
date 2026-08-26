"""闸门专用打分：只累计标题/路径命中，覆盖知识文档、指标目录与商家历史记忆三类语料。

设计见 openspec/changes/add-question-prefilter-gate/design.md D2、D4。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from app.knowledge.retrieval import KnowledgeRetrieval


@dataclass
class _Doc:
    source_path: str
    title: str
    content: str
    is_complete: bool = True


@dataclass
class _Metric:
    metric_code: str
    display_name: str


@dataclass
class _Memory:
    category: str
    content: str


class _KnowledgeRepo:
    def __init__(self, documents: list[_Doc]) -> None:
        self._documents = documents

    async def list_active(self) -> list[_Doc]:
        return self._documents


class _MetricRepo:
    def __init__(self, metrics: list[_Metric]) -> None:
        self._metrics = metrics

    async def list_active(self) -> list[_Metric]:
        return self._metrics


class _AllMemoryRepo:
    def __init__(self, memories: dict[UUID, list[_Memory]]) -> None:
        self._memories = memories

    async def list_all_for_merchant(self, merchant_id: UUID) -> list[_Memory]:
        return self._memories.get(merchant_id, [])


def _trade_document() -> _Doc:
    return _Doc(
        "业务/交易/业务流程/退货流程.md",
        "退款退货域",
        "本文档正文包含区别、什么、cnn、rnn 等词，用来验证正文不参与打分。",
    )


@pytest.mark.asyncio
async def test_title_hit_scores_above_zero() -> None:
    retrieval = KnowledgeRetrieval(_KnowledgeRepo([_trade_document()]))

    score = await retrieval.score_question(("退货",))

    assert score > 0


@pytest.mark.asyncio
async def test_content_only_hit_scores_zero() -> None:
    """正文命中的词不计分——否则任意问题都能靠长正文蹭到分数（design.md D2）。"""

    retrieval = KnowledgeRetrieval(_KnowledgeRepo([_trade_document()]))

    score = await retrieval.score_question(("区别", "cnn", "rnn"))

    assert score == 0


@pytest.mark.asyncio
async def test_metric_catalog_display_name_contributes_score() -> None:
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([]), metrics=_MetricRepo([_Metric("return_count", "退货量")])
    )

    score = await retrieval.score_question(("退货量",))

    assert score > 0


@pytest.mark.asyncio
async def test_merchant_memory_contributes_score() -> None:
    merchant_id = uuid4()
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([]),
        all_memories=_AllMemoryRepo({merchant_id: [_Memory("TRADE", "爆款商品是「云端保温杯」")]}),
        merchant_id=merchant_id,
    )

    score = await retrieval.score_question(("云端保温杯",))

    assert score > 0


@pytest.mark.asyncio
async def test_other_merchant_memory_does_not_contribute_score() -> None:
    """商家 B 自己没有这条记忆，只能靠团队知识库打分——用非空知识库把这一点
    和「语料完全不可用」（返回 None）的场景分开，避免两个断言互相掩盖。
    """

    merchant_a = uuid4()
    merchant_b = uuid4()
    retrieval = KnowledgeRetrieval(
        _KnowledgeRepo([_trade_document()]),
        all_memories=_AllMemoryRepo({merchant_a: [_Memory("TRADE", "爆款商品是「云端保温杯」")]}),
        merchant_id=merchant_b,
    )

    score = await retrieval.score_question(("云端保温杯",))

    assert score == 0


@pytest.mark.asyncio
async def test_unrelated_terms_score_zero() -> None:
    retrieval = KnowledgeRetrieval(_KnowledgeRepo([_trade_document()]))

    score = await retrieval.score_question(("cnn", "rnn", "区别"))

    assert score == 0


@pytest.mark.asyncio
async def test_entirely_empty_corpus_returns_none_for_fail_open() -> None:
    """`None` 与「打了分但没命中」（0 分）必须能区分：语料完全不可用时闸门要放行，
    而不是把它当成「问题与业务无关」拒绝——真实发生在全表 TRUNCATE 之后的测试
    数据库、以及知识库尚未导入的全新部署（spec「业务语料不可用时必须放行」）。
    """

    retrieval = KnowledgeRetrieval(_KnowledgeRepo([]))

    score = await retrieval.score_question(("退货",))

    assert score is None


@pytest.mark.asyncio
async def test_non_empty_corpus_without_a_match_returns_zero_not_none() -> None:
    """语料存在但没命中，必须真实返回 0（可拒绝），不能和「语料不可用」混淆。"""

    retrieval = KnowledgeRetrieval(_KnowledgeRepo([_trade_document()]))

    score = await retrieval.score_question(("cnn", "rnn"))

    assert score == 0
