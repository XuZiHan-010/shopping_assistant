"""N5 收费评测入口的静态范围与逐次调用上限。"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from app.core.config import Settings
from app.eval.acceptance_evidence import EvidenceBatch
from app.eval.n5_quality_real import MeteredDeepSeek, _case_id, quality_cases
from app.llm.client import LlmBudget
from app.llm.deepseek import DeepSeekLlmClient
from app.llm.fake import FakeLlmClient


def test_quality_batch_has_exactly_the_disclosed_25_chat_requests() -> None:
    cases = quality_cases()
    assert len(cases) == 25
    assert sum(case.id.startswith("QLT-N5-") for case in cases) == 8
    assert sum(len(case.turns) == 2 for case in cases) == 2
    assert all(case.turns[-1].request is not None for case in cases)


@pytest.mark.asyncio
async def test_meter_counts_upstream_calls_instead_of_http_turns(tmp_path: Path) -> None:
    batch = EvidenceBatch(tmp_path / "batch.jsonl", max_calls=2, max_tokens=50_000)
    fake = FakeLlmClient(responses=["one", "two", "three"])
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/borough_test",
        frontend_origin="http://localhost:5173",
        llm_max_output_tokens_per_call=64,
    )
    metered = MeteredDeepSeek(cast(DeepSeekLlmClient, fake), batch, settings)
    reset = _case_id.set("QLT-TEST")
    try:
        for _ in range(2):
            await metered.complete(
                system="system", user="user", fallback="fallback",
                budget=LlmBudget(max_calls=1, max_tokens=100),
            )
        with pytest.raises(ValueError, match="调用次数已达上限"):
            await metered.complete(
                system="system", user="user", fallback="fallback",
                budget=LlmBudget(max_calls=1, max_tokens=100),
            )
    finally:
        _case_id.reset(reset)
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_judge_uses_small_non_thinking_output_budget(tmp_path: Path) -> None:
    batch = EvidenceBatch(tmp_path / "judge.jsonl", max_calls=1, max_tokens=50_000)
    fake = FakeLlmClient(responses=["0.8"])
    settings = Settings(
        app_env="test",
        database_url="postgresql+psycopg://user:pass@localhost/borough_test",
        frontend_origin="http://localhost:5173",
        llm_max_output_tokens_per_call=512,
    )
    judge = MeteredDeepSeek(cast(DeepSeekLlmClient, fake), batch, settings, judge=True)
    await judge.complete(
        system="rubric", user="synthetic answer", fallback="0",
        budget=LlmBudget(max_calls=1, max_tokens=2000),
    )
    assert fake.call_options[0].thinking == "disabled"
