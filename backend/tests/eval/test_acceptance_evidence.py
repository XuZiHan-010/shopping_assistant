"""人工验收执行证据与跨日批次限额；只使用 Fake。"""

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.eval.acceptance_evidence import EvidenceBatch, validate_settings
from app.llm.client import LlmBudget, LlmResult
from app.llm.fake import FakeLlmClient


def test_batch_reopens_without_resetting_budget_or_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    batch = EvidenceBatch(path, max_calls=2, max_tokens=100)
    batch.reserve("one", 60)
    batch.finish("one", {"tokens": 40, "usage_known": True})
    reopened = EvidenceBatch(path, max_calls=2, max_tokens=100)
    with pytest.raises(ValueError, match="重复"):
        reopened.reserve("one", 10)
    with pytest.raises(ValueError, match="token"):
        reopened.reserve("two", 61)
    reopened.reserve("two", 60)
    reopened.finish("two", {"tokens": 5, "usage_known": True})
    with pytest.raises(ValueError, match="次数"):
        reopened.reserve("three", 1)


def test_unknown_or_interrupted_usage_stops_batch(tmp_path: Path) -> None:
    batch = EvidenceBatch(tmp_path / "batch.jsonl", max_calls=3, max_tokens=100)
    batch.reserve("one", 60)
    batch.finish("one", {"tokens": 0, "usage_known": False})
    with pytest.raises(ValueError, match=r"用量|未完成"):
        batch.reserve("two", 1)


def test_inflight_reservation_and_corrupt_log_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    batch = EvidenceBatch(path)
    batch.reserve("inflight", 60)
    with pytest.raises(ValueError, match="未完成"):
        EvidenceBatch(path).reserve("next", 1)
    with path.open("a", encoding="utf-8") as output:
        output.write('{"event":')
    with pytest.raises(ValueError):
        EvidenceBatch(path)


@pytest.mark.asyncio
async def test_exception_is_persisted_and_does_not_allow_retry(tmp_path: Path) -> None:
    class BrokenFake(FakeLlmClient):
        async def complete(self, **kwargs):
            raise RuntimeError("synthetic failure")

    path = tmp_path / "batch.jsonl"
    batch = EvidenceBatch(path)
    client = batch.client(BrokenFake(), "one", max_output_tokens=50)
    with pytest.raises(RuntimeError):
        await client.complete(system="", user="", fallback="", budget=LlmBudget(1, 100))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["result"]["error_type"] == "RuntimeError"
    assert rows[-1]["result"]["usage_known"] is False
    with pytest.raises(ValueError, match="未知用量"):
        batch.reserve("two", 1)


def test_changed_caps_and_concurrent_writer_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "batch.jsonl"
    batch = EvidenceBatch(path, max_calls=2, max_tokens=100)
    with pytest.raises(ValueError, match="上限"):
        EvidenceBatch(path, max_calls=3, max_tokens=100)
    path.with_suffix(".jsonl.lock").touch()
    with pytest.raises(FileExistsError):
        batch.reserve("one", 1)


@pytest.mark.asyncio
async def test_response_saved_before_next_call_and_error_keeps_reservation(tmp_path: Path) -> None:
    class KnownFake(FakeLlmClient):
        async def complete(self, **kwargs):
            return LlmResult(text='{"facts":[]}', tokens=5, degraded=False, usage_known=True)

    path = tmp_path / "batch.jsonl"
    batch = EvidenceBatch(path)
    client = batch.client(KnownFake(), "memory:one", max_output_tokens=50)
    await client.complete(system="系统", user="合成样本", fallback="", budget=LlmBudget(1, 100))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["result"]["text"] == '{"facts":[]}'
    assert rows[-1]["request_id"] == "memory:one"
    with pytest.raises(ValueError, match="重复"):
        await client.complete(system="", user="", fallback="", budget=LlmBudget(1, 100))


def test_real_preflight_locks_provider_protocol_and_memory_budget() -> None:
    base = dict(
        frontend_origin="http://localhost:5173",
        app_env="test",
        database_url="postgresql+psycopg://u:p@127.0.0.1:55454/acceptance_test",
        llm_api_key="test-only-fake-key",
        llm_model="deepseek-flash",
        llm_base_url="https://api.deepseek.com",
        llm_protocol="openai",
        memory_extraction_max_tokens=4000,
    )
    validate_settings(Settings(**base))
    for override in (
        {"llm_protocol": "anthropic"},
        {"memory_extraction_max_tokens": 5000},
        {"llm_base_url": "https://example.com"},
    ):
        with pytest.raises(ValueError):
            validate_settings(Settings(**(base | override)))


@pytest.mark.asyncio
@pytest.mark.parametrize("known,tokens", [(False, 5), (True, 999_999)])
async def test_last_call_unknown_usage_or_overrun_keeps_evidence_but_fails(
    tmp_path: Path, known: bool, tokens: int,
) -> None:
    class LastFake(FakeLlmClient):
        async def complete(self, **kwargs):
            return LlmResult(text="合成回答", tokens=tokens, degraded=False, usage_known=known)

    path = tmp_path / "batch.jsonl"
    client = EvidenceBatch(path, max_calls=1).client(LastFake(), "last", max_output_tokens=50)
    with pytest.raises(ValueError, match=r"用量|预留"):
        await client.complete(system="", user="", fallback="", budget=LlmBudget(1, 100))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["result"]["text"] == "合成回答"
