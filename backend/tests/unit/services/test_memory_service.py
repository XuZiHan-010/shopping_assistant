"""记忆压缩服务：标记注入、失败兜底、分类隔离。"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.llm.client import LlmBudget, LlmResult, LlmUnavailableError
from app.prompts.memory import MEMORY_MARKER
from app.services.memory_service import MemoryService


class _StubLlm:
    def __init__(self, text: str = "压缩后的记忆", *, raises: Exception | None = None) -> None:
        self._text = text
        self._raises = raises
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
    ) -> LlmResult:
        del system, user, fallback, budget
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return LlmResult(text=self._text, tokens=120, degraded=False)


class _StubRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[UUID, str, str]] = []

    async def upsert(self, *, merchant_id: UUID, category: str, content: str) -> None:
        self.saved.append((merchant_id, category, content))


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=2, max_tokens=8_000)


@pytest.mark.asyncio
async def test_marker_is_injected_when_model_output_lacks_it() -> None:
    repository = _StubRepository()
    service = MemoryService(_StubLlm("模型没写标记"), repository)

    content = await service.consolidate(
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="补充",
        history=[],
        budget=_budget(),
    )

    assert MEMORY_MARKER in content
    assert content.startswith("# TRADE")
    assert repository.saved[0][1:] == ("TRADE", content)


@pytest.mark.asyncio
async def test_model_output_with_marker_is_kept_verbatim() -> None:
    text = f"# TRADE\n\n## {MEMORY_MARKER}\n\n已经带标记"
    service = MemoryService(_StubLlm(text), _StubRepository())

    content = await service.consolidate(
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="",
        history=[],
        budget=_budget(),
    )

    assert content == text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [LlmUnavailableError("no key"), RuntimeError("boom")])
async def test_llm_failure_falls_back_to_deterministic_text(failure: Exception) -> None:
    repository = _StubRepository()
    service = MemoryService(_StubLlm(raises=failure), repository)

    content = await service.consolidate(
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        category="REFUND",
        manual_markdown="人工补充正文",
        history=[],
        budget=_budget(),
    )

    assert MEMORY_MARKER in content
    assert "人工补充正文" in content
    assert "更新时间：" in content
    assert repository.saved[0][1] == "REFUND"


@pytest.mark.asyncio
async def test_blank_model_output_falls_back() -> None:
    service = MemoryService(_StubLlm("   "), _StubRepository())

    content = await service.consolidate(
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        category="TRADE",
        manual_markdown="补充",
        history=[],
        budget=_budget(),
    )

    assert "补充" in content
    assert MEMORY_MARKER in content
