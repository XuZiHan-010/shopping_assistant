"""E5 RAG 检索评测（N4-C Task 1：关键词基线，PRD A7 / E5，契约 §6.14）。

先量再改：在不改任何检索代码的前提下，用现有关键词检索量出基线，作为后续向量与混合检索的对照。

- 基线 `platform_domain_retriever` 复现 N3 起 `search_rules` 的原路径：
  `tokenize` → `load_domain(PLATFORM_RULE, ...)`；
- `search_rules_retriever` 直接调用产品里的 `resolve_rule_search`
  （2026-10-01 起改为全文档检索），随产品代码变化；
- 语料为镜像内团队知识种子 `wiki_seed.json`（与部署时 `seed_wiki_documents` 落库的内容相同）；
- 只算确定性指标：Recall@3/5、MRR、nDCG@5（二值相关），以及「应当找不到」时的承认率；
- 引用正确率与回答忠实度需要 LLM 裁判（R3），未授权时在报告里标为待测；
- 报告只含聚合数与用例 ID，不含提问原文。

运行：`uv run python -m app.eval.rag_e5`（纯本地，零 LLM 调用）。

混合检索（N4-C Task 4）：
`uv run python -m app.eval.rag_e5 --embedding-model <模型> --min-similarity <τ>`
在内存里对种子语料分块、嵌入，再走产品的 `resolve_rule_search` 融合路径（RRF），
与关键词路径同场对比。
本地推理，不是 LLM 调用；首次运行会下载模型。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from app.agent.prefilter import tokenize
from app.knowledge.embedding import Embedder, FastEmbedEmbedder
from app.knowledge.index_versions import (
    IndexStatus,
    VectorSearchResult,
    chunk_document,
)
from app.knowledge.retrieval import KnowledgeRetrieval
from app.knowledge.wiki_seed import WikiSeedEntry, load_wiki_seed_entries
from app.schemas.chat import QuestionCategory

#: 评测集同时是索引版本切换的验证探针（§7.6），按 §5.6 单向依赖放在生产侧，评测从那里读。
DATASET: Final = Path(__file__).parents[1] / "knowledge/probes/n4_e5_rag.yaml"
NO_ANSWER: Final = "no_answer"
PENDING_METRICS: Final = ["citation_accuracy", "faithfulness"]

#: 一次检索的结果：按排名的文档路径，以及检索器是否声称命中。
Retriever = Callable[[str], Awaitable[tuple[list[str], bool]]]


def load_rag_cases(path: Path = DATASET) -> list[dict[str, Any]]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(cases, list)
    return cases


@dataclass
class _Document:
    """检索协议要求可写属性，冻结的 `WikiSeedEntry` 不满足，故转一层。"""

    source_path: str
    title: str
    content: str
    is_complete: bool


class _SeedRepository:
    """把镜像内知识种子当作「全部生效文档」，满足 `KnowledgeRetrieval` 的仓储协议。"""

    def __init__(self, entries: Sequence[WikiSeedEntry]) -> None:
        self._documents = [
            _Document(e.source_path, e.title, e.content, e.is_complete) for e in entries
        ]

    async def list_active(self) -> Sequence[_Document]:
        return self._documents


_SEED: Final = _SeedRepository(load_wiki_seed_entries())


async def platform_domain_retriever(query: str) -> tuple[list[str], bool]:
    """基线：N3 `search_rules` 原路径（固定平台规则域），2026-10-01 之前的生产行为。"""

    result = await KnowledgeRetrieval(_SEED).load_domain(
        QuestionCategory.PLATFORM_RULE, tokenize(query)
    )
    return [hit.source_path for hit in result.hits], result.matched


async def search_rules_retriever(query: str) -> tuple[list[str], bool]:
    """当前生产路径：直接调用 `search_rules` 工具的检索函数。"""

    from app.tools.merchant.definitions import resolve_rule_search

    output = await resolve_rule_search(query, retrieval=KnowledgeRetrieval(_SEED))
    payload = output.payload
    assert isinstance(payload, Mapping)
    return [str(hit["source_path"]) for hit in payload["hits"]], bool(payload["matched"])


class InMemoryVectorSearch:
    """评测用向量召回：与 `VectorIndexSearch` 同一接口与同一聚合方式（文档取最高块相似度）。"""

    def __init__(self, embedder: Embedder, *, min_similarity: float, limit: int = 10) -> None:
        chunks = [
            chunk
            for entry in load_wiki_seed_entries()
            for chunk in chunk_document(entry.source_path, entry.title, entry.content)
        ]
        self._paths = [chunk.source_path for chunk in chunks]
        self._vectors = [_unit(v) for v in embedder.embed_passages([c.content for c in chunks])]
        self._embedder = embedder
        self._min_similarity = min_similarity
        self._limit = limit

    async def search(self, query: str) -> VectorSearchResult:
        q = _unit(self._embedder.embed_queries([query])[0])
        best: dict[str, float] = {}
        for path, vector in zip(self._paths, self._vectors, strict=True):
            similarity = sum(a * b for a, b in zip(q, vector, strict=True))
            best[path] = max(best.get(path, -1.0), similarity)
        ranked = sorted(best.items(), key=lambda kv: -kv[1])[: self._limit]
        return VectorSearchResult(
            IndexStatus.FRESH,
            tuple((p, s) for p, s in ranked if s >= self._min_similarity),
            version_id=0,
        )


def _unit(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def hybrid_retriever_for(vector: InMemoryVectorSearch) -> Retriever:
    """混合检索：产品 `search_rules` 的检索函数，注入向量召回。"""

    async def hybrid_retriever(query: str) -> tuple[list[str], bool]:
        from app.tools.merchant.definitions import resolve_rule_search

        output = await resolve_rule_search(
            query,
            retrieval=KnowledgeRetrieval(_SEED),
            vector=vector,
        )
        payload = output.payload
        assert isinstance(payload, Mapping)
        return [str(hit["source_path"]) for hit in payload["hits"]], bool(payload["matched"])

    return hybrid_retriever


_CATEGORY_OF: Final = {e.source_path: e.category for e in load_wiki_seed_entries()}


def oracle_domain_retriever_for(
    cases: Sequence[Mapping[str, Any]],
) -> Retriever:
    """诊断对照：假设域路由完全正确，用期望文档所属的业务域检索（应找不到的问题仍用平台规则域）。

    只用于把「域过滤造成的损失」与「关键词匹配本身的上限」分开，不代表任何可上线的检索方式。
    """

    category_by_query = {
        str(case["query"]): QuestionCategory(
            _CATEGORY_OF[case["expected"][0]] if case["expected"] else "PLATFORM_RULE"
        )
        for case in cases
    }

    async def oracle_domain_retriever(query: str) -> tuple[list[str], bool]:
        result = await KnowledgeRetrieval(_SEED).load_domain(
            category_by_query[query], tokenize(query)
        )
        return [hit.source_path for hit in result.hits], result.matched

    return oracle_domain_retriever


def recall_at_k(ranked: Sequence[str], expected: Sequence[str], *, k: int) -> float:
    if not expected:
        return 0.0
    top = set(ranked[:k])
    return sum(doc in top for doc in expected) / len(expected)


def reciprocal_rank(ranked: Sequence[str], expected: Sequence[str]) -> float:
    relevant = set(expected)
    for position, doc in enumerate(ranked, start=1):
        if doc in relevant:
            return 1 / position
    return 0.0


def ndcg_at_k(ranked: Sequence[str], expected: Sequence[str], *, k: int) -> float:
    relevant = set(expected)
    dcg = sum(
        1 / math.log2(position + 1)
        for position, doc in enumerate(ranked[:k], start=1)
        if doc in relevant
    )
    ideal = sum(1 / math.log2(position + 1) for position in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


async def evaluate(cases: Sequence[Mapping[str, Any]], retrieve: Retriever) -> dict[str, Any]:
    rows: list[tuple[str, dict[str, float]]] = []
    rejections = no_answer = 0
    returned: list[int] = []
    false_hits: list[str] = []
    missed: list[str] = []
    for case in cases:
        ranked, matched = await retrieve(str(case["query"]))
        returned.append(len(ranked))
        expected = list(case["expected"])
        if case["kind"] == NO_ANSWER:
            no_answer += 1
            if matched and ranked:
                false_hits.append(str(case["id"]))
            else:
                rejections += 1
            continue
        scores = {
            "recall_at_3": recall_at_k(ranked, expected, k=3),
            "recall_at_5": recall_at_k(ranked, expected, k=5),
            "mrr": reciprocal_rank(ranked, expected),
            "ndcg_at_5": ndcg_at_k(ranked, expected, k=5),
        }
        if scores["recall_at_5"] == 0.0:
            missed.append(str(case["id"]))
        rows.append((str(case["kind"]), scores))

    kinds = sorted({kind for kind, _ in rows})
    return {
        "retriever": getattr(retrieve, "__name__", "retriever"),
        "answerable_cases": len(rows),
        "no_answer_cases": no_answer,
        "overall": _mean([scores for _, scores in rows]),
        "by_kind": {kind: _mean([s for k, s in rows if k == kind]) for kind in kinds},
        "no_answer_rejection_rate": rejections / no_answer if no_answer else 1.0,
        "mean_documents_returned": sum(returned) / len(returned) if returned else 0.0,
        "missed_case_ids": missed,
        "false_hit_case_ids": false_hits,
        "pending": list(PENDING_METRICS),
    }


def _mean(rows: Sequence[Mapping[str, float]]) -> dict[str, float]:
    keys = ("recall_at_3", "recall_at_5", "mrr", "ndcg_at_5")
    if not rows:
        return {key: 0.0 for key in keys} | {"cases": 0}
    return {key: round(sum(row[key] for row in rows) / len(rows), 4) for key in keys} | {
        "cases": len(rows)
    }


async def _main(embedding_model: str | None, min_similarity: float, cache_dir: str | None) -> None:
    cases = load_rag_cases()
    reports = [
        await evaluate(cases, platform_domain_retriever),
        await evaluate(cases, search_rules_retriever),
        await evaluate(cases, oracle_domain_retriever_for(cases)),
    ]
    if embedding_model:
        vector = InMemoryVectorSearch(
            FastEmbedEmbedder(embedding_model, cache_dir=cache_dir), min_similarity=min_similarity
        )
        report = await evaluate(cases, hybrid_retriever_for(vector))
        report |= {"embedding_model": embedding_model, "min_similarity": min_similarity}
        reports.append(report)
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="E5 RAG 检索评测（零 LLM 调用）")
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--min-similarity", type=float, default=0.4)
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args()
    asyncio.run(_main(args.embedding_model, args.min_similarity, args.cache_dir))
