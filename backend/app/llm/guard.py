"""唯一的 LLM 费用防护入口。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.analytics.dates import business_today
from app.core.config import Settings
from app.llm.client import (
    LlmBudget,
    LlmClient,
    LlmDailyBudgetExceededError,
    LlmResult,
    LlmUnavailableError,
)
from app.repositories.llm_budget import LlmBudgetRepository


class CostGuardProtocol(Protocol):
    daily_cap_hit: bool

    async def remaining(self) -> int: ...


def estimate_call_tokens(
    *, system: str, user: str, remaining_request_tokens: int, max_output_tokens: int
) -> int:
    return max(
        len(system) + len(user) + min(max_output_tokens, max(remaining_request_tokens, 0)), 1
    )


class LlmCostGuard:
    def __init__(
        self,
        inner: LlmClient,
        repository: LlmBudgetRepository,
        settings: Settings,
        *,
        request_id: str,
        merchant_id: UUID,
    ) -> None:
        self._inner, self._repository, self._settings = inner, repository, settings
        self._request_id, self._merchant_id = request_id, merchant_id
        self.daily_cap_hit = False

    def is_configured(self) -> bool:
        return self._inner.is_configured()

    async def remaining(self) -> int:
        usage_date = business_today(datetime.now(UTC), timezone=self._settings.business_timezone)
        snapshot = await self._repository.snapshot(usage_date=usage_date)
        return max(self._settings.llm_daily_budget_tokens - snapshot.consumed_tokens, 0)

    async def complete(
        self, *, system: str, user: str, fallback: str, budget: LlmBudget
    ) -> LlmResult:
        if not self._inner.is_configured():
            raise LlmUnavailableError("LLM 客户端未配置")
        estimated = estimate_call_tokens(
            system=system,
            user=user,
            remaining_request_tokens=budget.max_tokens - budget.tokens,
            max_output_tokens=self._settings.llm_max_output_tokens_per_call,
        )
        usage_date = business_today(datetime.now(UTC), timezone=self._settings.business_timezone)
        reserved = await self._repository.reserve(
            usage_date=usage_date, tokens=estimated, budget=self._settings.llm_daily_budget_tokens
        )
        if reserved is None:
            self.daily_cap_hit = True
            await self._repository.record_usage(
                usage_date=usage_date,
                request_id=self._request_id,
                model=self._settings.llm_model,
                tokens=0,
                status="BUDGET_REJECTED",
                merchant_id=self._merchant_id,
            )
            raise LlmDailyBudgetExceededError
        try:
            result = await self._inner.complete(
                system=system, user=user, fallback=fallback, budget=budget
            )
        except BaseException:
            await self._repository.record_usage(
                usage_date=usage_date,
                request_id=self._request_id,
                model=self._settings.llm_model,
                tokens=estimated,
                status="FAILED",
                merchant_id=self._merchant_id,
            )
            raise
        if result.degraded and result.tokens == 0:
            await self._repository.record_usage(
                usage_date=usage_date,
                request_id=self._request_id,
                model=self._settings.llm_model,
                tokens=estimated,
                status="FAILED",
                merchant_id=self._merchant_id,
            )
            return result
        await self._repository.reconcile(usage_date=usage_date, delta=result.tokens - estimated)
        await self._repository.record_usage(
            usage_date=usage_date,
            request_id=self._request_id,
            model=self._settings.llm_model,
            tokens=result.tokens,
            status="SUCCEEDED",
            merchant_id=self._merchant_id,
        )
        return result
