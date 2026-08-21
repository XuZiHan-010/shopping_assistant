"""管理员手动重压商家记忆。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LlmBudget, LlmClient
from app.repositories.answer import AnswerRepository
from app.repositories.audit import AuditRepository
from app.repositories.memory import MerchantMemoryRepository
from app.schemas.knowledge import MemoryCompressResponse
from app.services.memory_service import MemoryService

_COMPRESS_MAX_TOKENS = 4_000
_HISTORY_LIMIT = 80


class MemoryAdminService:
    """编排审计、历史读取与商家记忆压缩。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm: LlmClient,
        audit: AuditRepository,
    ) -> None:
        self._session = session
        self._llm = llm
        self._audit = audit

    async def compress(
        self,
        *,
        merchant_id: UUID,
        display_name: str,
        category: str,
        manual_markdown: str,
        request_id: str,
    ) -> MemoryCompressResponse:
        history = await AnswerRepository(self._session).recent_answers_for_category(
            merchant_id=merchant_id,
            category=category,
            limit=_HISTORY_LIMIT,
        )
        await self._audit.record_admin_action(
            merchant_id=merchant_id,
            event_type="ADMIN_MEMORY_COMPRESS",
            resource_type="MERCHANT_MEMORY",
            resource_id=category,
            request_id=request_id,
            metadata={"history_rows": str(len(history))},
        )
        consolidation = await MemoryService(
            self._llm, MerchantMemoryRepository(self._session)
        ).consolidate(
            merchant_id=merchant_id,
            merchant_display=display_name,
            category=category,
            manual_markdown=manual_markdown,
            history=history,
            budget=LlmBudget(max_calls=1, max_tokens=_COMPRESS_MAX_TOKENS),
        )
        await self._session.commit()
        return MemoryCompressResponse(
            merchant_id=merchant_id,
            category=category,
            content=consolidation.content,
            history_rows=len(history),
            degraded=consolidation.degraded,
            degraded_reason=consolidation.degraded_reason,
        )
