"""N4-C 混合召回单测（PRD A7，契约 §6.14，计划 Task 4）：RRF、分块、探针 Recall、融合与降级标注。"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest

from app.knowledge.fusion import rrf_fuse
from app.knowledge.index_versions import (
    INDEX_FALLBACK_REASON,
    INDEX_STALE_REASON,
    Chunk,
    IndexStatus,
    Probe,
    VectorSearchResult,
    chunk_document,
    load_probes,
    probe_recall_at_5,
)
from app.knowledge.retrieval import KnowledgeRetrieval
from app.tools.merchant.definitions import resolve_rule_search


@dataclass
class _Doc:
    source_path: str
    title: str
    content: str
    is_complete: bool = True


class _Repo:
    def __init__(self, documents: list[_Doc]) -> None:
        self._documents = documents

    async def list_active(self) -> list[_Doc]:
        return self._documents


class _FixedVector:
    def __init__(self, result: VectorSearchResult) -> None:
        self._result = result
        self.queries: list[str] = []

    async def search(self, query: str) -> VectorSearchResult:
        self.queries.append(query)
        return self._result


def test_rrf_needs_no_score_normalization() -> None:
    kw = [("d1", 12.7), ("d2", 3.1)]  # 关键词加权分
    vec = [("d2", 0.91), ("d3", 0.88)]  # 余弦相似度
    assert [d for d, _ in rrf_fuse(kw, vec)][:2] == ["d2", "d1"]


def test_search_documents_keeps_keyword_only_call_shape() -> None:
    """N3 调用方（`search_documents(keywords)`）与 v1 `load_domain` 不需要改调用方式。"""

    params = inspect.signature(KnowledgeRetrieval.search_documents).parameters
    assert list(params)[:2] == ["self", "keywords"]
    assert params["vector_ranking"].kind is inspect.Parameter.KEYWORD_ONLY
    assert list(inspect.signature(KnowledgeRetrieval.load_domain).parameters) == [
        "self",
        "category",
        "keywords",
    ]


def test_chunks_carry_title_and_split_long_documents() -> None:
    body = "\n\n".join(f"第{i}段" + "字" * 150 for i in range(5))
    chunks = chunk_document("业务/a.md", "标题A", body)
    assert len(chunks) > 1
    assert all(c.content.startswith("标题A\n") for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunk_document("业务/b.md", "空", "") == [Chunk("业务/b.md", 0, "空\n")]


def test_probe_recall_ignores_probes_whose_documents_were_deleted() -> None:
    chunks = [Chunk("a", 0, "a"), Chunk("b", 0, "b")]
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    probes = [Probe("qa", ("a",)), Probe("gone", ("deleted",))]
    assert probe_recall_at_5(probes, chunks, vectors, [[1.0, 0.0], [0.0, 1.0]]) == 1.0
    assert probe_recall_at_5([Probe("gone", ("deleted",))], chunks, vectors, [[1.0, 0.0]]) is None


def test_probes_are_answerable_e5_cases() -> None:
    probes = load_probes()
    assert len(probes) >= 50
    assert all(p.expected for p in probes)


@pytest.mark.asyncio
async def test_vector_only_hit_is_returned_with_live_content() -> None:
    """关键词完全没命中（口语化/跨语言）时，向量召回仍能把文档带回来，正文取最新文档。"""

    docs = [_Doc("业务/退货.md", "退货流程", "退货退款的处理步骤（最新版）")]
    vector = _FixedVector(
        VectorSearchResult(IndexStatus.FRESH, (("业务/退货.md", 0.8),), version_id=3)
    )
    out = await resolve_rule_search(
        "买家不想要了咋整", retrieval=KnowledgeRetrieval(_Repo(docs)), vector=vector
    )
    assert out.payload["matched"] is True
    assert out.payload["hits"][0]["content"] == "退货退款的处理步骤（最新版）"
    assert out.payload["retrieval"] == "HYBRID"
    assert out.payload["index_degraded_reason"] is None


@pytest.mark.asyncio
async def test_deleted_document_left_in_index_is_not_returned() -> None:
    vector = _FixedVector(
        VectorSearchResult(IndexStatus.STALE, (("业务/已删除.md", 0.9),), version_id=3)
    )
    out = await resolve_rule_search(
        "已删除的规则", retrieval=KnowledgeRetrieval(_Repo([])), vector=vector
    )
    assert out.payload["matched"] is False
    assert out.payload["index_degraded_reason"] == INDEX_STALE_REASON


@pytest.mark.asyncio
async def test_unavailable_index_falls_back_to_keyword_and_says_so() -> None:
    docs = [_Doc("平台规则/after_sale.md", "售后规则", "退货运费由平台承担。")]
    vector = _FixedVector(VectorSearchResult(IndexStatus.UNAVAILABLE, (), None))
    out = await resolve_rule_search(
        "退货运费谁出", retrieval=KnowledgeRetrieval(_Repo(docs)), vector=vector
    )
    assert out.payload["matched"] is True
    assert out.payload["retrieval"] == "KEYWORD_ONLY"
    assert out.payload["index_degraded_reason"] == INDEX_FALLBACK_REASON


@pytest.mark.asyncio
async def test_without_vector_search_the_tool_reports_keyword_fallback() -> None:
    out = await resolve_rule_search("退货运费谁出", retrieval=KnowledgeRetrieval(_Repo([])))
    assert out.payload["index_degraded_reason"] == INDEX_FALLBACK_REASON


@pytest.mark.asyncio
async def test_exact_field_identifier_outranks_generic_status_matches() -> None:
    """字段名查询：含完整标识符的文档排第一，不被只命中「status / 状态」的泛化文档淹没。"""

    docs = [
        _Doc("业务/退货.md", "退货名词", "refund_status_name 退款状态、退货状态、订单状态"),
        _Doc("业务/理赔.md", "理赔名词", "repay_status_name：赔付状态取值为待赔付、已赔付"),
    ]
    out = await resolve_rule_search(
        "repay_status_name 的取值", retrieval=KnowledgeRetrieval(_Repo(docs))
    )
    assert out.payload["hits"][0]["source_path"] == "业务/理赔.md"


@pytest.mark.asyncio
async def test_ascii_terms_match_whole_words_only() -> None:
    """英文片段按词边界匹配：`or` 不再命中 `order`，`spu` 仍命中 `spu_status_name`。"""

    retrieval = KnowledgeRetrieval(
        _Repo(
            [_Doc("业务/商品.md", "商品", "spu_status_name 商品状态"), _Doc("x.md", "x", "order")]
        )
    )
    result = await retrieval.search_documents(["or"])
    assert result.matched is False
    hit = await retrieval.search_documents(["spu", "商品"])
    assert [h.source_path for h in hit.hits] == ["业务/商品.md"]


@pytest.mark.asyncio
async def test_index_readme_does_not_win_ties() -> None:
    docs = [
        _Doc("index/README.md", "说明", "退货 流程"),
        _Doc("业务/a.md", "说明", "退货 流程"),
    ]
    result = await KnowledgeRetrieval(_Repo(docs)).search_documents(["退货", "流程"])
    assert result.hits[0].source_path == "业务/a.md"
