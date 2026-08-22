"""后台记忆沉淀：不阻塞、不外溢、尊重每日预算。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.memory_agent import MemoryAgent, build_manual_markdown


class _RecordingBackground:
    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.tasks.append((func, args, kwargs))

    async def run_all(self) -> None:
        for func, args, kwargs in self.tasks:
            await func(*args, **kwargs)


def test_manual_markdown_carries_all_reference_fields() -> None:
    markdown = build_manual_markdown(
        question="上月成交额",
        category="TRADE",
        source_tables=["orders"],
        quality_notes=["无"],
        suggestions=["看看退款"],
        export_id="exp-1",
        answer="上月成交额为 X",
    )
    for field in (
        "question",
        "category",
        "source_tables",
        "quality_notes",
        "suggested_questions",
        "csv_export",
    ):
        assert field in markdown
    assert markdown.lstrip().startswith("## 本轮自动沉淀")
    assert "上月成交额为 X" in markdown


def test_submit_does_not_run_inline() -> None:
    background = _RecordingBackground()
    agent = MemoryAgent(
        background=background,
        database=None,
        settings=None,
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        request_id="test-request",
    )
    agent.submit(
        category="TRADE",
        question="上月成交额",
        answer="X",
        source_tables=[],
        quality_notes=[],
        suggestions=[],
        export_id=None,
    )
    assert len(background.tasks) == 1


def test_submit_is_skipped_for_unknown_category() -> None:
    background = _RecordingBackground()
    agent = MemoryAgent(
        background=background,
        database=None,
        settings=None,
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        request_id="test-request",
    )
    agent.submit(
        category="UNKNOWN",
        question="你好",
        answer="你好",
        source_tables=[],
        quality_notes=[],
        suggestions=[],
        export_id=None,
    )
    assert background.tasks == []


@pytest.mark.asyncio
async def test_task_failure_never_escapes() -> None:
    background = _RecordingBackground()

    class _ExplodingDatabase:
        def session(self):
            raise RuntimeError("数据库炸了")

    agent = MemoryAgent(
        background=background,
        database=_ExplodingDatabase(),
        settings=None,
        merchant_id=uuid4(),
        merchant_display="Borough商家100",
        request_id="test-request",
    )
    agent.submit(
        category="TRADE",
        question="上月成交额",
        answer="X",
        source_tables=[],
        quality_notes=[],
        suggestions=[],
        export_id=None,
    )
    await background.run_all()
