"""唯一的 LLM 费用防护入口。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Literal, Protocol, cast
from uuid import UUID

from app.analytics.dates import business_today
from app.core.config import Settings
from app.llm.client import (
    DEFAULT_LLM_CALL_OPTIONS,
    LlmBudget,
    LlmCallOptions,
    LlmClient,
    LlmDailyBudgetExceededError,
    LlmMessage,
    LlmResult,
    LlmStreamEvent,
    LlmTurn,
    LlmUnavailableError,
    TextDelta,
    ToolSchema,
    TurnComplete,
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
        merchant_id: UUID | None,
        purpose: Literal["AGENT", "LOCALIZATION"] = "AGENT",
    ) -> None:
        """`merchant_id` 放宽为可空：`/api/admin/*` 的全局调用（如本地化的
        GLOBAL 作用域翻译）没有商家上下文，`llm_usage.merchant_id` 本身也早已
        可空（ON DELETE SET NULL）。`purpose` 区分主 Agent 流程与 Task 4 的
        本地化通道，写入 `llm_usage.purpose`，供预算看板分开统计两条费用。
        """

        self._inner, self._repository, self._settings = inner, repository, settings
        self._request_id, self._merchant_id = request_id, merchant_id
        self._purpose = purpose
        self.daily_cap_hit = False

    def is_configured(self) -> bool:
        return self._inner.is_configured()

    async def remaining(self) -> int:
        usage_date = business_today(datetime.now(UTC), timezone=self._settings.business_timezone)
        snapshot = await self._repository.snapshot(usage_date=usage_date)
        return max(self._settings.llm_daily_budget_tokens - snapshot.consumed_tokens, 0)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        fallback: str,
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
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
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                reserved_tokens=0,
                usage_known=True,
                failure_kind=None,
                status="BUDGET_REJECTED",
                merchant_id=self._merchant_id,
                purpose=self._purpose,
            )
            raise LlmDailyBudgetExceededError
        try:
            result = await self._inner.complete(
                system=system, user=user, fallback=fallback, budget=budget, options=options
            )
        except BaseException:
            await self._repository.record_usage(
                usage_date=usage_date,
                request_id=self._request_id,
                model=self._settings.llm_model,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                reserved_tokens=estimated,
                usage_known=False,
                failure_kind=None,
                status="FAILED",
                merchant_id=self._merchant_id,
                purpose=self._purpose,
            )
            raise
        if result.usage_known:
            await self._repository.reconcile(usage_date=usage_date, delta=result.tokens - estimated)
        await self._repository.record_usage(
            usage_date=usage_date,
            request_id=self._request_id,
            model=self._settings.llm_model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.tokens,
            reserved_tokens=estimated,
            usage_known=result.usage_known,
            failure_kind=result.failure_kind.value if result.failure_kind is not None else None,
            status="FAILED" if result.degraded else "SUCCEEDED",
            merchant_id=self._merchant_id,
            purpose=self._purpose,
        )
        return result

    async def converse(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> LlmTurn:
        """v2 工具循环的每一次模型决策都要过同一道费用闸（R3、§6.10）。

        与 `complete()` 共用预留 → 调用 → 对账 → 落用量这套顺序：循环里一个回合
        可能连调多次模型，如果只有 v1 路径记账，工具循环的开销在预算看板上就是隐形的。
        内层客户端没有 `converse()`（例如未配置的替身）时按未配置处理，
        不让调用方以为自己拿到了一个能用的对话客户端。
        """

        inner = getattr(self._inner, "converse", None)
        if not self._inner.is_configured() or inner is None:
            raise LlmUnavailableError("LLM 客户端未配置或不支持工具调用")
        estimated = self._estimate_turn(messages, tools, budget)
        usage_date = business_today(datetime.now(UTC), timezone=self._settings.business_timezone)
        reserved = await self._repository.reserve(
            usage_date=usage_date, tokens=estimated, budget=self._settings.llm_daily_budget_tokens
        )
        if reserved is None:
            self.daily_cap_hit = True
            await self._record(usage_date, status="BUDGET_REJECTED", reserved=0)
            raise LlmDailyBudgetExceededError
        try:
            turn = cast(
                LlmTurn,
                await inner(messages=messages, tools=tools, budget=budget, options=options),
            )
        except BaseException:
            await self._record(usage_date, status="FAILED", reserved=estimated, usage_known=False)
            raise
        if turn.usage_known:
            await self._repository.reconcile(usage_date=usage_date, delta=turn.tokens - estimated)
        await self._record(
            usage_date,
            status="FAILED" if turn.degraded else "SUCCEEDED",
            reserved=estimated,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            total_tokens=turn.tokens,
            usage_known=turn.usage_known,
            failure_kind=turn.failure_kind.value if turn.failure_kind is not None else None,
        )
        return turn

    async def converse_stream(
        self,
        *,
        messages: list[LlmMessage],
        tools: list[ToolSchema],
        budget: LlmBudget,
        options: LlmCallOptions = DEFAULT_LLM_CALL_OPTIONS,
    ) -> AsyncIterator[LlmStreamEvent]:
        """流式回合：用量在终止事件 `TurnComplete` 上一次性记账。

        逐段增量不记账是有意的——增量没有可靠的 token 计数，半路累加会让用量
        依赖分片粒度；断流时 `TurnComplete` 仍然会到达（带降级标记），记账不会漏。
        """

        turn = await self.converse(messages=messages, tools=tools, budget=budget, options=options)
        if turn.text:
            yield TextDelta(text=turn.text)
        yield TurnComplete(turn=turn)

    def _estimate_turn(
        self, messages: list[LlmMessage], tools: list[ToolSchema], budget: LlmBudget
    ) -> int:
        """按字符数粗估，与 `estimate_call_tokens()` 同一套口径，外加工具 schema 的体积。"""

        system = "".join(message.content for message in messages)
        user = "".join(tool.name + tool.description for tool in tools)
        return estimate_call_tokens(
            system=system,
            user=user,
            remaining_request_tokens=budget.max_tokens - budget.tokens,
            max_output_tokens=self._settings.llm_max_output_tokens_per_call,
        )

    async def _record(
        self,
        usage_date: date,
        *,
        status: str,
        reserved: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        usage_known: bool = True,
        failure_kind: str | None = None,
    ) -> None:
        await self._repository.record_usage(
            usage_date=usage_date,
            request_id=self._request_id,
            model=self._settings.llm_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            reserved_tokens=reserved,
            usage_known=usage_known,
            failure_kind=failure_kind,
            status=status,
            merchant_id=self._merchant_id,
            purpose=self._purpose,
        )
