"""唯一的 LLM 费用防护入口。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from typing import Literal, Protocol, cast
from uuid import UUID

from app.analytics.dates import business_today
from app.core.config import Settings
from app.core.session import SessionRole
from app.llm.budget_scope import BudgetScope, budget_scopes
from app.llm.client import (
    DEFAULT_LLM_CALL_OPTIONS,
    LlmBudget,
    LlmBudgetExceededError,
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


class ScopedBudgetRepository(Protocol):
    async def reserve_scoped(
        self, *, usage_date: date, tokens: int, scopes: Sequence[BudgetScope]
    ) -> str | None: ...

    async def reconcile_scoped(
        self, *, usage_date: date, delta: int, scope_keys: Sequence[str]
    ) -> None: ...


class CostGuardProtocol(Protocol):
    daily_cap_hit: bool

    async def remaining(self) -> int: ...


def estimate_call_tokens(
    *, system: str, user: str, remaining_request_tokens: int, max_output_tokens: int
) -> int:
    # UTF-8 字节数保守覆盖中英文与表情的输入 token；额外预留协议包装开销。
    return max(
        len(system.encode("utf-8"))
        + len(user.encode("utf-8"))
        + 256
        + min(max_output_tokens, max(remaining_request_tokens, 0)),
        1,
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
        purpose: Literal["AGENT", "LOCALIZATION", "MEMORY"] = "AGENT",
        role: SessionRole | None = None,
    ) -> None:
        """`merchant_id` 放宽为可空：`/api/admin/*` 的全局调用（如本地化的
        GLOBAL 作用域翻译）没有商家上下文，`llm_usage.merchant_id` 本身也早已
        可空（ON DELETE SET NULL）。`purpose` 区分主 Agent 流程与 Task 4 的
        本地化通道，写入 `llm_usage.purpose`，供预算看板分开统计两条费用。
        """

        self._inner, self._repository, self._settings = inner, repository, settings
        self._request_id, self._merchant_id = request_id, merchant_id
        self._purpose = purpose
        self._scopes = budget_scopes(settings, role, merchant_id)
        self._role = role.value if role is not None else None
        self.daily_cap_hit = False
        #: 熔断时是哪一级耗尽（`GLOBAL` / `ROLE:*` / `SHOP:*`），供看板与降级说明；未熔断为 None。
        self.exhausted_scope: str | None = None

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
        self._check_request_budget(budget)
        input_upper = len(system.encode("utf-8")) + len(user.encode("utf-8")) + 256
        estimated, call_options = self._fit_call(input_upper, budget, options)
        usage_date = business_today(datetime.now(UTC), timezone=self._settings.business_timezone)
        if not await self._reserve(usage_date, estimated):
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
                role=self._role,
            )
            raise LlmDailyBudgetExceededError
        try:
            result = await self._inner.complete(
                system=system, user=user, fallback=fallback, budget=budget, options=call_options
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
                role=self._role,
            )
            raise
        if result.usage_known:
            await self._reconcile(usage_date, result.tokens - estimated)
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
            role=self._role,
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
        self._check_request_budget(budget)
        estimated, call_options = self._fit_call(
            self._turn_input_upper(messages, tools), budget, options
        )
        usage_date = business_today(datetime.now(UTC), timezone=self._settings.business_timezone)
        if not await self._reserve(usage_date, estimated):
            await self._record(usage_date, status="BUDGET_REJECTED", reserved=0)
            raise LlmDailyBudgetExceededError
        try:
            turn = cast(
                LlmTurn,
                await inner(messages=messages, tools=tools, budget=budget, options=call_options),
            )
        except BaseException:
            await self._record(usage_date, status="FAILED", reserved=estimated, usage_known=False)
            raise
        if turn.usage_known:
            await self._reconcile(usage_date, turn.tokens - estimated)
        await self._record(
            usage_date,
            status="FAILED" if turn.degraded else "SUCCEEDED",
            reserved=estimated,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            total_tokens=turn.tokens,
            usage_known=turn.usage_known,
            failure_kind=turn.failure_kind.value if turn.failure_kind is not None else None,
            cache_hit_tokens=turn.cache_hit_tokens,
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

    @staticmethod
    def _turn_input_upper(messages: list[LlmMessage], tools: list[ToolSchema]) -> int:
        """完整序列化后的 UTF-8 字节数 + 协议包装余量。"""
        payload = json.dumps(
            {
                "messages": [asdict(message) for message in messages],
                "tools": [asdict(tool) for tool in tools],
            },
            ensure_ascii=False,
            default=str,
        )
        return len(payload.encode("utf-8")) + 256

    def _estimate_turn(
        self, messages: list[LlmMessage], tools: list[ToolSchema], budget: LlmBudget
    ) -> int:
        return self._turn_input_upper(messages, tools) + min(
            self._settings.llm_max_output_tokens_per_call,
            max(budget.max_tokens - budget.tokens, 0),
        )

    def _fit_call(
        self, input_upper: int, budget: LlmBudget, options: LlmCallOptions
    ) -> tuple[int, LlmCallOptions]:
        remaining = budget.max_tokens - budget.tokens
        available_output = remaining - input_upper
        requested_output = min(
            self._settings.llm_max_output_tokens_per_call,
            options.max_output_tokens
            if options.max_output_tokens is not None
            else self._settings.llm_max_output_tokens_per_call,
        )
        output_limit = min(requested_output, available_output)
        if output_limit <= 0:
            raise LlmBudgetExceededError("单请求 LLM token 余额不足以覆盖输入与输出")
        return input_upper + output_limit, replace(options, max_output_tokens=output_limit)

    @staticmethod
    def _check_request_budget(budget: LlmBudget) -> None:
        if budget.calls >= budget.max_calls or budget.tokens >= budget.max_tokens:
            raise LlmBudgetExceededError("单请求 LLM 预算已达上限")

    async def _reserve(self, usage_date: date, tokens: int) -> bool:
        """预算检查在发出请求之前：任一级耗尽即整体不扣、不发请求。"""

        exhausted = await self._repository.reserve_scoped(
            usage_date=usage_date, tokens=tokens, scopes=self._scopes
        )
        if exhausted is None:
            return True
        self.daily_cap_hit = True
        self.exhausted_scope = exhausted
        return False

    async def _reconcile(self, usage_date: date, delta: int) -> None:
        await self._repository.reconcile_scoped(
            usage_date=usage_date, delta=delta, scope_keys=[scope.key for scope in self._scopes]
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
        cache_hit_tokens: int | None = None,
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
            role=self._role,
            cache_hit_tokens=cache_hit_tokens,
        )
