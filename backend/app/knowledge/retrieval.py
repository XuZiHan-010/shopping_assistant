"""两层团队知识检索。

索引层在业务域未知时仅提供目录与规则词汇；正文层在业务域确定后提供事实。
参考实现从文件系统匹配“路径 + 正文”，本项目改存 PostgreSQL（Railway 容器磁盘
不适合运行时可编辑知识），故保留 ``source_path`` 列完成相同行为。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.knowledge.domains import (
    ACTION_RULE_TERMS,
    DOMAIN_KEYWORDS,
    INDEX_PATH_MARKERS,
    MAX_KNOWLEDGE_CHARS,
)
from app.schemas.chat import QuestionCategory

_METRIC_SUFFIX = re.compile(r"(指标|明细|数据|情况|趋势|数量|金额|次数|量|数)$")
_MIN_STEM_LENGTH = 2

#: 所有业务域的名词合集，作为复合问法拆词的「业务词」受控表。
_BUSINESS_TERMS: tuple[str, ...] = tuple(
    {term for terms in DOMAIN_KEYWORDS.values() for term in terms}
)

#: 相关性权重：标题最能代表文档主题，路径次之，正文里出现一次最弱。
_TITLE_WEIGHT = 3
_PATH_WEIGHT = 2
_CONTENT_WEIGHT = 1

#: 复合问法命中过多时只保留前若干篇，避免整域文档灌进模型上下文。
_TOP_N = 3


class KnowledgeSource(StrEnum):
    """检索来源，取值与参考实现的 LLM_WIKI_SOURCE 标记一致。"""

    MAINTAINED = "maintained"
    MEMORY_FALLBACK = "memory-fallback"
    NONE = "none"


def strip_metric_suffix(keyword: str) -> str:
    """剥掉中文指标问法的词尾，避免“退货量”错过“退货”知识。"""

    normalized = keyword.strip()
    stem = _METRIC_SUFFIX.sub("", normalized)
    return stem if len(stem) >= _MIN_STEM_LENGTH else normalized


@dataclass(frozen=True)
class KnowledgeHit:
    source_path: str
    title: str
    content: str
    is_complete: bool


@dataclass(frozen=True)
class KnowledgeResult:
    text: str
    hits: tuple[KnowledgeHit, ...]
    matched: bool
    has_incomplete: bool
    source: KnowledgeSource = KnowledgeSource.NONE


_EMPTY = KnowledgeResult(text="", hits=(), matched=False, has_incomplete=False)


class _DocumentLike(Protocol):
    source_path: str
    title: str
    content: str
    is_complete: bool


class _RepositoryLike(Protocol):
    async def list_active(self) -> Sequence[_DocumentLike]: ...


class _MemoryLike(Protocol):
    category: str
    content: str


class _MemoryRepositoryLike(Protocol):
    async def list_for_merchant(
        self, merchant_id: UUID, category: str
    ) -> Sequence[_MemoryLike]: ...


class KnowledgeRetrieval:
    def __init__(
        self,
        repository: _RepositoryLike,
        *,
        memories: _MemoryRepositoryLike | None = None,
        merchant_id: UUID | None = None,
    ) -> None:
        self._repository = repository
        self._memories = memories
        self._merchant_id = merchant_id

    async def load_index(self) -> KnowledgeResult:
        """业务域未知时，只加载目录与规则文档。"""

        documents = await self._repository.list_active()
        return _render(
            [
                document
                for document in documents
                if any(marker in document.source_path.lower() for marker in INDEX_PATH_MARKERS)
            ],
            KnowledgeSource.MAINTAINED,
        )

    async def load_domain(
        self,
        category: QuestionCategory,
        keywords: Sequence[str],
    ) -> KnowledgeResult:
        """业务域确定后按别名与意图关键词收窄正文。"""

        documents = await self._repository.list_active()
        aliases = DOMAIN_KEYWORDS.get(category, ())
        hits = [
            document for document in documents if _is_domain_document(document, category, aliases)
        ]
        if keywords:
            hits = _narrow_by_keywords(hits, keywords)

        if hits:
            return _render(hits, KnowledgeSource.MAINTAINED)
        return await self._load_memory_fallback(category)

    async def _load_memory_fallback(self, category: QuestionCategory) -> KnowledgeResult:
        if self._memories is None or self._merchant_id is None:
            return _EMPTY
        memories = await self._memories.list_for_merchant(self._merchant_id, str(category))
        if not memories:
            return _EMPTY
        return _render_memories(memories, category)


def _haystack(document: _DocumentLike) -> str:
    return f"{document.source_path} {document.content}".lower()


def _contains_any(haystack: str, keywords: Sequence[str]) -> bool:
    return any(keyword.lower() in haystack for keyword in keywords if keyword.strip())


def _is_domain_document(
    document: _DocumentLike,
    category: QuestionCategory,
    aliases: Sequence[str],
) -> bool:
    """排除分类索引，避免它们以含多域别名的正文冒充领域事实。"""

    source_path = document.source_path.lower()
    if category is not QuestionCategory.PLATFORM_RULE and any(
        marker in source_path for marker in INDEX_PATH_MARKERS
    ):
        return False
    return _contains_any(_haystack(document), aliases)


def _weighted_fields(document: _DocumentLike) -> tuple[str, str, str]:
    return (
        document.title.lower(),
        document.source_path.lower(),
        document.content.lower(),
    )


def _decompose(keywords: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """把问法拆成受控词表里的「业务词」与「动作/规则词」。

    只在两张已知词表里找子串，不做通用分词（D1 裁定）。返回两个元组，
    调用方据此判断这是不是一个「业务词 + 动作/规则词」的复合问法。
    """

    text = " ".join(keyword.strip().lower() for keyword in keywords if keyword.strip())
    business = tuple(term for term in _BUSINESS_TERMS if term.lower() in text)
    action_rule = tuple(term for term in ACTION_RULE_TERMS if term.lower() in text)
    return business, action_rule


def _relevance_score(document: _DocumentLike, terms: Sequence[str]) -> int:
    title, path, content = _weighted_fields(document)
    score = 0
    for raw in terms:
        term = raw.lower()
        if term in title:
            score += _TITLE_WEIGHT
        if term in path:
            score += _PATH_WEIGHT
        if term in content:
            score += _CONTENT_WEIGHT
    return score


def _narrow_by_keywords(
    documents: list[_DocumentLike],
    keywords: Sequence[str],
) -> list[_DocumentLike]:
    """按意图关键词收窄正文层。

    复合问法（同时给出业务词与动作/规则词）走「两张词表各命中至少一个」的
    门槛再按相关性取前 N 篇；否则维持原有的「命中任一关键词」行为。

    只对复合问法启用更严的门槛，是为了不改变「退货量」这类单业务词问法的召回：
    对它们要求动作词会让本来能答的问题变成未命中。
    """

    business, action_rule = _decompose(keywords)
    if not business or not action_rule:
        return [
            document for document in documents if _matches_keywords(_haystack(document), keywords)
        ]

    # 「商品定价」这类同域文档只共享泛业务词「商品」，缺动作/规则词，必须排除，
    # 否则关键词过滤在该域内退化为空过滤（2026-08-22 实测）。
    gated = [
        document
        for document in documents
        if _contains_any(" ".join(_weighted_fields(document)), business)
        and _contains_any(" ".join(_weighted_fields(document)), action_rule)
    ]
    terms = (*business, *action_rule)
    # sorted 是稳定排序：同分文档保持仓储给出的原始顺序，结果可复现。
    return sorted(gated, key=lambda document: -_relevance_score(document, terms))[:_TOP_N]


def _matches_keywords(haystack: str, keywords: Sequence[str]) -> bool:
    for raw in keywords:
        keyword = raw.strip().lower()
        if not keyword:
            continue
        if keyword in haystack:
            return True
        stem = strip_metric_suffix(keyword)
        if stem != keyword and stem in haystack:
            return True
    return False


def _render(documents: list[_DocumentLike], source: KnowledgeSource) -> KnowledgeResult:
    if not documents:
        return _EMPTY

    chunks: list[str] = []
    total = 0
    hits: list[KnowledgeHit] = []
    for document in documents:
        block = f"## {document.title}\n（来源：{document.source_path}）\n{document.content}\n"
        if total + len(block) > MAX_KNOWLEDGE_CHARS:
            break
        chunks.append(block)
        total += len(block)
        hits.append(
            KnowledgeHit(
                source_path=document.source_path,
                title=document.title,
                content=document.content,
                is_complete=document.is_complete,
            )
        )

    if not hits:
        first = documents[0]
        hits = [
            KnowledgeHit(
                source_path=first.source_path,
                title=first.title,
                content=first.content,
                is_complete=first.is_complete,
            )
        ]
        chunks = [first.content[:MAX_KNOWLEDGE_CHARS]]

    return KnowledgeResult(
        text=(f"[LLM_WIKI_SOURCE={source.value}]\n" + "\n".join(chunks))[:MAX_KNOWLEDGE_CHARS],
        hits=tuple(hits),
        matched=True,
        has_incomplete=any(not hit.is_complete for hit in hits),
        source=source,
    )


def _render_memories(
    memories: Sequence[_MemoryLike], category: QuestionCategory
) -> KnowledgeResult:
    source = KnowledgeSource.MEMORY_FALLBACK
    hits = tuple(
        KnowledgeHit(
            source_path=f"memory/{category}",
            title=str(category),
            content=memory.content,
            is_complete=True,
        )
        for memory in memories
    )
    blocks = [f"## {memory.category}\n{memory.content}\n" for memory in memories]
    return KnowledgeResult(
        text=(f"[LLM_WIKI_SOURCE={source.value}]\n" + "\n".join(blocks))[:MAX_KNOWLEDGE_CHARS],
        hits=hits,
        matched=True,
        has_incomplete=False,
        source=source,
    )
