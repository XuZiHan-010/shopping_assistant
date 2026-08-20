"""记忆压缩服务。"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from app.llm.client import LlmBudget, LlmClient
from app.prompts.memory import (
    MEMORY_MARKER,
    MEMORY_SYSTEM_PROMPT,
    build_fallback_memory,
    build_memory_prompt,
)

logger = logging.getLogger(__name__)


class _MemoryRepositoryLike(Protocol):
    async def upsert(self, *, merchant_id: UUID, category: str, content: str) -> object: ...


class MemoryService:
    def __init__(self, llm: LlmClient, repository: _MemoryRepositoryLike) -> None:
        self._llm = llm
        self._repository = repository

    async def consolidate(
        self,
        *,
        merchant_id: UUID,
        merchant_display: str,
        category: str,
        manual_markdown: str,
        history: list[dict[str, object]],
        budget: LlmBudget,
        use_llm: bool = True,
    ) -> str:
        fallback = build_fallback_memory(category=category, manual_markdown=manual_markdown)
        content = fallback
        if use_llm:
            prompt = build_memory_prompt(
                merchant_display=merchant_display,
                category=category,
                manual_markdown=manual_markdown,
                history=history,
            )
            try:
                result = await self._llm.complete(
                    system=MEMORY_SYSTEM_PROMPT,
                    user=prompt,
                    fallback=fallback,
                    budget=budget,
                )
                if not result.degraded and result.text.strip():
                    content = result.text
            except Exception:
                logger.warning(
                    "记忆压缩调用模型失败，改写确定性兜底文本",
                    extra={"category": category},
                    exc_info=True,
                )

        content = _ensure_marker(content, category)
        await self._repository.upsert(
            merchant_id=merchant_id,
            category=category,
            content=content,
        )
        return content


def _ensure_marker(content: str, category: str) -> str:
    """确保记忆带有读侧排除所需的自动沉淀标记。"""

    if MEMORY_MARKER in content:
        return content
    return f"# {category}\n\n## {MEMORY_MARKER}\n\n{content}"
