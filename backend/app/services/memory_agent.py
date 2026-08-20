"""回答完成后的后台记忆沉淀调度。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.db.session import Database
from app.llm.client import LlmBudget
from app.prompts.memory import MEMORY_MARKER

logger = logging.getLogger(__name__)
_MEMORY_TASK_MAX_TOKENS = 4_000
_SKIPPED_CATEGORIES = frozenset({"UNKNOWN", ""})

_MANUAL_TEMPLATE = """## {marker}

- question: {question}
- category: {category}
- source_tables: {source_tables}
- quality_notes: {quality_notes}
- suggested_questions: {suggestions}
- csv_export: {export_id}

### answer
{answer}
"""


def build_manual_markdown(
    *,
    question: str,
    category: str,
    source_tables: list[str],
    quality_notes: list[str],
    suggestions: list[str],
    export_id: str | None,
    answer: str,
) -> str:
    return _MANUAL_TEMPLATE.format(
        marker=MEMORY_MARKER,
        question=question,
        category=category,
        source_tables=source_tables,
        quality_notes=quality_notes,
        suggestions=suggestions,
        export_id=export_id or "",
        answer=answer,
    )


class _BackgroundLike(Protocol):
    def add_task(
        self,
        func: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> None: ...


class MemoryAgent:
    def __init__(
        self,
        *,
        background: _BackgroundLike,
        database: Database | None,
        settings: Settings | None,
        merchant_id: UUID,
        merchant_display: str,
        request_id: str,
    ) -> None:
        self._background = background
        self._database = database
        self._settings = settings
        self._merchant_id = merchant_id
        self._merchant_display = merchant_display
        self._request_id = request_id

    def submit(
        self,
        *,
        category: str,
        question: str,
        answer: str,
        source_tables: list[str],
        quality_notes: list[str],
        suggestions: list[str],
        export_id: str | None,
    ) -> None:
        if category in _SKIPPED_CATEGORIES:
            return
        manual = build_manual_markdown(
            question=question,
            category=category,
            source_tables=source_tables,
            quality_notes=quality_notes,
            suggestions=suggestions,
            export_id=export_id,
            answer=answer,
        )
        self._background.add_task(self._consolidate, category, manual)

    async def _consolidate(self, category: str, manual: str) -> None:
        try:
            if self._database is None:
                return
            from app.llm.client import LlmClient
            from app.llm.deepseek import DeepSeekLlmClient
            from app.llm.fake import FakeLlmClient
            from app.llm.guard import LlmCostGuard
            from app.repositories.llm_budget import LlmBudgetRepository
            from app.repositories.memory import MerchantMemoryRepository
            from app.services.memory_service import MemoryService

            llm: LlmClient
            if self._settings is not None and self._settings.llm_api_key:
                # 必须复用聊天主链路同一套 LlmCostGuard/LlmBudgetRepository，
                # 而不是自行判断「本轮请求构造时是否已耗尽」——那是一张构造期快照，
                # 永远读不到本轮问答自己刚刚花掉的额度。包一层 guard 后，每日预算
                # 检查和 llm_usage 记账都实时发生在这次真正调用的时候。
                llm = LlmCostGuard(
                    DeepSeekLlmClient(self._settings),
                    LlmBudgetRepository(self._database),
                    self._settings,
                    request_id=f"{self._request_id}:memory:{category}",
                    merchant_id=self._merchant_id,
                )
            else:
                llm = FakeLlmClient(configured=False)
            async with self._database.session() as session:
                service = MemoryService(llm, MerchantMemoryRepository(session))
                await service.consolidate(
                    merchant_id=self._merchant_id,
                    merchant_display=self._merchant_display,
                    category=category,
                    manual_markdown=manual,
                    history=[],
                    budget=LlmBudget(max_calls=1, max_tokens=_MEMORY_TASK_MAX_TOKENS),
                )
                await session.commit()
        except Exception:
            logger.warning("记忆沉淀失败", extra={"category": category}, exc_info=True)
