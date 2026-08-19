"""LlmCostGuard 的原子预算防护行为。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

import pytest

from app.core.config import AppEnvironment, Settings
from app.llm.client import (
    DEFAULT_LLM_CALL_OPTIONS,
    LlmBudget,
    LlmCallOptions,
    LlmClient,
    LlmDailyBudgetExceededError,
    LlmFailureKind,
    LlmResult,
    LlmUnavailableError,
)
from app.llm.fake import FakeLlmClient
from app.llm.guard import LlmCostGuard

MERCHANT_ID = UUID("00000000-0000-0000-0000-000000000001")


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnvironment.TEST,
        "database_url": "postgresql+psycopg://user:pass@localhost/test",
        "frontend_origin": "http://localhost:5173",
        "llm_daily_budget_tokens": 1_000,
        "llm_max_output_tokens_per_call": 200,
    }
    values.update(overrides)
    return Settings(
        **values,
    )


@dataclass
class _ReserveCall:
    usage_date: date
    tokens: int
    budget: int


@dataclass
class _ReconcileCall:
    usage_date: date
    delta: int


@dataclass
class _RecordUsageCall:
    usage_date: date
    request_id: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    reserved_tokens: int
    usage_known: bool
    failure_kind: str | None
    status: str
    merchant_id: UUID | None


class FakeLlmBudgetRepository:
    """不连数据库的 `LlmBudgetRepository` 替身，记录每次调用供断言。"""

    def __init__(self, *, reserve_returns: list[int | None]) -> None:
        self._reserve_returns = list(reserve_returns)
        self.reserve_calls: list[_ReserveCall] = []
        self.reconcile_calls: list[_ReconcileCall] = []
        self.record_usage_calls: list[_RecordUsageCall] = []

    async def reserve(self, *, usage_date: date, tokens: int, budget: int) -> int | None:
        self.reserve_calls.append(_ReserveCall(usage_date, tokens, budget))
        return self._reserve_returns.pop(0)

    async def reconcile(self, *, usage_date: date, delta: int) -> None:
        self.reconcile_calls.append(_ReconcileCall(usage_date, delta))

    async def snapshot(self, *, usage_date: date) -> object:
        raise AssertionError("guard.complete 不应调用 snapshot")

    async def record_usage(
        self,
        *,
        usage_date: date,
        request_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        reserved_tokens: int,
        usage_known: bool,
        failure_kind: str | None,
        status: str,
        merchant_id: UUID | None,
    ) -> None:
        self.record_usage_calls.append(
            _RecordUsageCall(
                usage_date,
                request_id,
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                reserved_tokens,
                usage_known,
                failure_kind,
                status,
                merchant_id,
            )
        )


class StubInnerClient:
    """被 `LlmCostGuard` 包裹的下游 LLM 客户端替身。"""

    def __init__(
        self, *, result: LlmResult | None = None, error: BaseException | None = None
    ) -> None:
        self._result = result
        self._error = error
        self.calls = 0
        self.call_options: list[LlmCallOptions] = []

    def is_configured(self) -> bool:
        return True

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmResult:
        self.calls += 1
        self.call_options.append(options)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _guard(
    repository: FakeLlmBudgetRepository, inner: LlmClient, *, settings: Settings | None = None
) -> LlmCostGuard:
    return LlmCostGuard(
        inner,
        repository,  # type: ignore[arg-type]
        settings or _settings(),
        request_id="req-1",
        merchant_id=MERCHANT_ID,
    )


@pytest.mark.asyncio
async def test_complete_does_not_reserve_budget_when_inner_client_unconfigured() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[])
    guard = LlmCostGuard(
        FakeLlmClient(configured=False),
        repository,  # type: ignore[arg-type]
        _settings(),
        request_id="req-unconfigured",
        merchant_id=MERCHANT_ID,
    )
    budget = LlmBudget(max_calls=6, max_tokens=1_000)

    with pytest.raises(LlmUnavailableError):
        await guard.complete(system="s", user="u", fallback="f", budget=budget)

    assert repository.reserve_calls == []
    assert repository.record_usage_calls == []


@pytest.mark.asyncio
async def test_complete_reconciles_estimate_to_actual_tokens_and_records_success() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[50])
    inner = StubInnerClient(
        result=LlmResult(text="ok", tokens=30, degraded=False, usage_known=True)
    )
    guard = _guard(repository, inner)

    result = await guard.complete(
        system="s", user="u", fallback="fallback", budget=LlmBudget(max_calls=4, max_tokens=8_000)
    )

    assert result.text == "ok"
    assert guard.daily_cap_hit is False
    assert repository.reconcile_calls == [
        _ReconcileCall(
            repository.reserve_calls[0].usage_date, 30 - repository.reserve_calls[0].tokens
        )
    ]
    assert repository.record_usage_calls[-1].status == "SUCCEEDED"
    assert repository.record_usage_calls[-1].total_tokens == 30


@pytest.mark.asyncio
async def test_complete_raises_and_sets_cap_hit_when_reserve_rejected() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[None])
    inner = StubInnerClient(
        result=LlmResult(text="unused", tokens=0, degraded=False, usage_known=True)
    )
    guard = _guard(repository, inner)

    with pytest.raises(LlmDailyBudgetExceededError):
        await guard.complete(
            system="s",
            user="u",
            fallback="fallback",
            budget=LlmBudget(max_calls=4, max_tokens=8_000),
        )

    assert guard.daily_cap_hit is True
    assert inner.calls == 0
    assert repository.record_usage_calls == [
        _RecordUsageCall(
            repository.reserve_calls[0].usage_date,
            "req-1",
            "deepseek-v4-flash",
            0,
            0,
            0,
            0,
            True,
            None,
            "BUDGET_REJECTED",
            MERCHANT_ID,
        )
    ]


@pytest.mark.asyncio
async def test_complete_still_bills_estimate_when_inner_call_fails() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[50])
    inner = StubInnerClient(error=RuntimeError("下游超时"))
    guard = _guard(repository, inner)

    with pytest.raises(RuntimeError, match="下游超时"):
        await guard.complete(
            system="s",
            user="u",
            fallback="fallback",
            budget=LlmBudget(max_calls=4, max_tokens=8_000),
        )

    assert repository.reconcile_calls == []
    assert repository.record_usage_calls[-1].status == "FAILED"
    assert repository.record_usage_calls[-1].total_tokens == 0
    assert repository.record_usage_calls[-1].reserved_tokens == repository.reserve_calls[0].tokens


@pytest.mark.asyncio
async def test_complete_records_failed_without_reconcile_when_degraded_zero_tokens() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[50])
    inner = StubInnerClient(result=LlmResult(text="fallback", tokens=0, degraded=True))
    guard = _guard(repository, inner)

    result = await guard.complete(
        system="s", user="u", fallback="fallback", budget=LlmBudget(max_calls=4, max_tokens=8_000)
    )

    assert result.degraded is True
    assert repository.reconcile_calls == []
    assert repository.record_usage_calls[-1].status == "FAILED"


@pytest.mark.asyncio
async def test_usage_row_records_real_prompt_and_completion_tokens() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[3_000])
    inner = StubInnerClient(
        result=LlmResult(
            text="ok",
            tokens=2_778,
            degraded=False,
            input_tokens=508,
            output_tokens=2_270,
            usage_known=True,
        )
    )

    await _guard(repository, inner).complete(
        system="s", user="u", fallback="fallback", budget=LlmBudget(max_calls=4, max_tokens=8_000)
    )
    row = repository.record_usage_calls[-1]

    assert row.input_tokens == 508
    assert row.output_tokens == 2_270
    assert row.total_tokens == 2_778


@pytest.mark.asyncio
async def test_http_401_records_known_zero_tokens_and_releases_reservation() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[500])
    inner = StubInnerClient(
        result=LlmResult(
            text="fallback",
            tokens=0,
            degraded=True,
            failure_kind=LlmFailureKind.HTTP_401,
            usage_known=True,
        )
    )

    await _guard(repository, inner).complete(
        system="s", user="u", fallback="fallback", budget=LlmBudget(max_calls=4, max_tokens=8_000)
    )
    row = repository.record_usage_calls[-1]

    assert row.total_tokens == 0
    assert row.status == "FAILED"
    assert row.failure_kind == "HTTP_401"
    assert row.usage_known is True
    assert row.reserved_tokens == repository.reserve_calls[0].tokens
    assert repository.reconcile_calls[-1].delta == -repository.reserve_calls[0].tokens


@pytest.mark.asyncio
async def test_timeout_keeps_conservative_reservation_and_marks_usage_unknown() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[500])
    inner = StubInnerClient(
        result=LlmResult(
            text="fallback",
            tokens=0,
            degraded=True,
            failure_kind=LlmFailureKind.TIMEOUT,
            usage_known=False,
        )
    )

    await _guard(repository, inner).complete(
        system="s", user="u", fallback="fallback", budget=LlmBudget(max_calls=4, max_tokens=8_000)
    )
    row = repository.record_usage_calls[-1]

    assert row.total_tokens == 0
    assert row.failure_kind == "TIMEOUT"
    assert row.usage_known is False
    assert row.reserved_tokens == repository.reserve_calls[0].tokens
    assert repository.reconcile_calls == []


@pytest.mark.asyncio
async def test_success_payload_without_usage_never_releases_reservation() -> None:
    repository = FakeLlmBudgetRepository(reserve_returns=[500])
    inner = StubInnerClient(
        result=LlmResult(text='{"answer":"ok"}', tokens=0, degraded=False, usage_known=False)
    )

    await _guard(repository, inner).complete(
        system="s", user="u", fallback="fallback", budget=LlmBudget(max_calls=4, max_tokens=8_000)
    )

    assert repository.reconcile_calls == []
    assert repository.record_usage_calls[-1].reserved_tokens == repository.reserve_calls[0].tokens
    assert repository.record_usage_calls[-1].usage_known is False


@pytest.mark.asyncio
async def test_remaining_subtracts_snapshot_from_daily_budget() -> None:
    class SnapshotOnlyRepository(FakeLlmBudgetRepository):
        async def snapshot(self, *, usage_date: date) -> object:
            @dataclass
            class _Snapshot:
                consumed_tokens: int
                call_count: int

            return _Snapshot(consumed_tokens=400, call_count=3)

    repository = SnapshotOnlyRepository(reserve_returns=[])
    guard = _guard(repository, StubInnerClient(), settings=_settings(llm_daily_budget_tokens=1_000))

    assert await guard.remaining() == 600
