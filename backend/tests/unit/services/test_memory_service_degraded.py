"""consolidate() 必须让调用方看见「模型没跑」。R7：降级不能伪装成成功。"""

from __future__ import annotations

from uuid import UUID

import pytest

from app.llm.client import LlmBudget
from app.llm.fake import FakeLlmClient
from app.prompts.memory import MEMORY_MARKER
from app.services.memory_service import MemoryService

MERCHANT_ID = UUID("00000000-0000-0000-0000-0000000000a1")


class _StubRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[UUID, str, str]] = []

    async def upsert(self, *, merchant_id: UUID, category: str, content: str) -> object:
        self.saved.append((merchant_id, category, content))
        return object()


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=1, max_tokens=4_000)


@pytest.mark.asyncio
async def test_consolidate_reports_degraded_when_model_unavailable() -> None:
    repository = _StubRepository()
    service = MemoryService(FakeLlmClient(configured=False), repository)

    result = await service.consolidate(
        merchant_id=MERCHANT_ID,
        merchant_display="测试商家",
        category="TRADE",
        manual_markdown="人工补充：大促退款按申请日计。",
        history=[],
        budget=_budget(),
    )

    assert result.degraded is True
    assert result.degraded_reason
    assert "大促退款按申请日计" in result.content
    assert MEMORY_MARKER in result.content
    assert repository.saved


@pytest.mark.asyncio
async def test_consolidate_reports_not_degraded_on_success() -> None:
    repository = _StubRepository()
    service = MemoryService(
        FakeLlmClient(responses=["# TRADE\n\n## 本轮自动沉淀\n\n压缩后的画像"]),
        repository,
    )

    result = await service.consolidate(
        merchant_id=MERCHANT_ID,
        merchant_display="测试商家",
        category="TRADE",
        manual_markdown="人工补充",
        history=[{"question": "上周成交额多少", "answer": "12 万元"}],
        budget=_budget(),
    )

    assert result.degraded is False
    assert result.degraded_reason is None
    assert "压缩后的画像" in result.content
