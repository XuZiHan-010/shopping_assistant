import hashlib
import json

import pytest

from app.eval.acceptance_recovery import RecoveryBatch, result_digest
from app.llm.client import LlmBudget, LlmResult
from app.llm.fake import FakeLlmClient


def failed_batch(tmp_path):
    batch = RecoveryBatch(tmp_path / "batch.jsonl", max_calls=3, max_tokens=100)
    batch.reserve("failed", 60)
    result = {"error_type": "LlmBudgetExceededError", "tokens": 60, "usage_known": False}
    batch.finish("failed", result)
    return batch, result


def test_resolution_preserves_unknown_and_counts_full_reserved_budget(tmp_path):
    batch, result = failed_batch(tmp_path)
    before = batch.path.read_bytes()
    batch.resolve_budget_error("failed", result_digest(result))
    assert batch.path.read_bytes().startswith(before)
    assert batch._rows()[2]["result"]["usage_known"] is False
    with pytest.raises(ValueError, match="token"):
        batch.reserve("next", 41)
    batch.reserve("next", 40)
    with pytest.raises(ValueError, match="重复"):
        batch.reserve("failed", 1)


def test_manual_resolution_requires_exact_hash_and_cannot_repeat(tmp_path):
    batch, result = failed_batch(tmp_path)
    with pytest.raises(ValueError, match="哈希"):
        batch.resolve_budget_error("failed", hashlib.sha256(b"wrong").hexdigest())
    with pytest.raises(ValueError, match="未知"):
        batch.reserve("next", 1)
    batch.resolve_budget_error("failed", result_digest(result))
    with pytest.raises(ValueError, match="重复"):
        batch.resolve_budget_error("failed", result_digest(result))


def test_unreviewed_error_is_never_resolved(tmp_path):
    batch = RecoveryBatch(tmp_path / "batch.jsonl")
    batch.reserve("failed", 60)
    result = {"error_type": "TimeoutError", "tokens": 60, "usage_known": False}
    batch.finish("failed", result)
    with pytest.raises(ValueError, match="预算异常"):
        batch.resolve_budget_error("failed", result_digest(result))


def test_result_digest_is_stable():
    result = {"tokens": 1, "usage_known": False}
    assert (
        result_digest(result)
        == hashlib.sha256(
            json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
    )


@pytest.mark.asyncio
async def test_replay_makes_no_new_model_call_or_ledger_entry(tmp_path):
    class KnownFake(FakeLlmClient):
        async def complete(self, **kwargs):
            self.invoked = True
            return LlmResult(text="saved", tokens=5, degraded=False, usage_known=True)

    batch = RecoveryBatch(tmp_path / "batch.jsonl")
    first = batch.client(KnownFake(), "one", max_output_tokens=50)
    kwargs = dict(system="s", user="u", fallback="", budget=LlmBudget(1, 100))
    await first.complete(**kwargs)
    original = batch.path.read_bytes()
    unused = FakeLlmClient()
    replay = batch.client(unused, "one", max_output_tokens=50)
    result = await replay.complete(**kwargs)
    assert result.text == "saved"
    assert unused.calls == []
    assert batch.path.read_bytes() == original


@pytest.mark.asyncio
async def test_replay_ignores_only_paired_random_fence_ids(tmp_path):
    from app.agent.loop.fencing import fence

    class KnownFake(FakeLlmClient):
        async def complete(self, **kwargs):
            return LlmResult(text="saved", tokens=5, degraded=False, usage_known=True)

    batch = RecoveryBatch(tmp_path / "batch.jsonl")
    first = batch.client(KnownFake(), "fenced", max_output_tokens=50)
    kwargs = dict(system="s", user=fence("same", source="customer"), fallback="",
                  budget=LlmBudget(1, 100))
    await first.complete(**kwargs)
    original = batch.path.read_bytes()
    unused = FakeLlmClient()
    replay = batch.client(unused, "fenced", max_output_tokens=50)
    result = await replay.complete(**(kwargs | {"user": fence("same", source="customer")}))
    assert result.text == "saved" and unused.calls == []
    with pytest.raises(ValueError, match="不匹配"):
        await replay.complete(**(kwargs | {"user": fence("changed", source="customer")}))
    assert batch.path.read_bytes() == original
    with pytest.raises(ValueError, match="不匹配"):
        await replay.complete(**(kwargs | {"user": "changed"}))
    assert unused.calls == []
