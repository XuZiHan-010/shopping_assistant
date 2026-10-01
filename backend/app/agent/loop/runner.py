"""v2 工具调用主循环（§6.10，PRD A2）。

一个回合 = 若干轮「模型决策 → 闸门 → 工具」，直到模型作答或任一上限触顶；作答后先跑确定性校验，
再（可选）交独立 Reviewer 复核，不通过则在同一份预算内重新生成。规则逐条对应测试：

1. 五项上限任一触顶即停，按 `stop_reason` 如实披露，不静默截断；
2. 触顶返回已获得的部分结果 + 降级标注（R7），不伪装成完整回答；
3. `FatalToolError` 立即终止整个回合：原样抛出，不重试、不降级、不进 Reviewer；
4. 只有 `READ_ONLY` 且 `parallelizable` 的调用并行；含写操作的批次强制串行，且写操作一旦开始
   不被墙钟或断开打断（半途取消会留下「不知道是否已提交」的事务）；
5. 确定性校验先于 LLM Reviewer（Q16）；
6. 工具结果与顾客消息进提示词前经 `fencing.fence()` 围栏（A11）；唯一例外是 `load_skill` 返回的
   受信 Skill（§6.11）：工具名为 `load_skill` **且** payload 类型为注册表产出的 `SkillSpec`、
   且该 Skill 属于当前会话角色时才免围栏——不看文本里有没有 `<skill>` 标记；
   单回合加载数超过 `max_skill_loads` 的调用被拒绝并告知模型，回合继续（PRD A4）；
7. 客户端断开（`cancel` 被置位）时停止后续 LLM 调用；已完成的部分随 `LoopOutcome`
   交给调用方落库；
8. 每次工具轮决策前估算上下文，超过 `LoopLimits.compaction.trigger_tokens` 时按配置策略
   压缩（§6.12）；压缩真正改变上下文时发出 `ContextCompacted`（SSE `step`），不静默发生。
   摘要调用走同一份预算；确定性校验的来源（`sources` 与完整 `ToolResult`）在回合开始时固定，
   不受压缩影响。

本模块与冻结的 `app.agent.graph` 不共享代码路径（§5.6）。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol

from app.agent.loop.checks import DEFAULT_CHECKS, DeterministicCheck
from app.agent.loop.compaction import (
    CompactionOutcome,
    CompactionStrategy,
    estimate_tokens,
)
from app.agent.loop.compaction.pruning import prune_tool_results
from app.agent.loop.compaction.summarization import summarize_early_context
from app.agent.loop.fencing import FENCE_POLICY, fence
from app.agent.loop.limits import LoopLimits
from app.core.errors import ErrorCode
from app.core.session import SessionRole
from app.llm.client import (
    ConversationalLlmClient,
    LlmBudget,
    LlmBudgetError,
    LlmDailyBudgetExceededError,
    LlmMessage,
    LlmToolCall,
    LlmTurn,
    LlmUnavailableError,
    ToolSchema,
)
from app.localization.locales import SupportedLocale
from app.schemas.chat import QualityStatus
from app.services.quality_types import DegradeReason
from app.skills.spec import LOAD_SKILL_TOOL, SkillSpec, render_skill_message
from app.tools.errors import FatalToolError
from app.tools.gates import AdmittedCall, ToolGates
from app.tools.registry import tool_role_for
from app.tools.types import (
    DISPLAY_STATUS,
    ToolContext,
    ToolDisplay,
    ToolOutcome,
    ToolResult,
    WritePolicy,
)

logger = logging.getLogger(__name__)

StopReason = Literal[
    "COMPLETED",
    "MAX_TURNS",
    "MAX_TOOL_CALLS",
    "BUDGET",
    "WALL_CLOCK",
    "UPSTREAM",
    "CANCELLED",
    "FATAL",  # 循环本身不返回它：致命错误以 FatalToolError 抛出，留给路由层落库时记录
]

_STOP_DEGRADE: Final[dict[StopReason, DegradeReason]] = {
    "MAX_TURNS": DegradeReason.LIMIT,
    "MAX_TOOL_CALLS": DegradeReason.LIMIT,
    "BUDGET": DegradeReason.BUDGET,
    "WALL_CLOCK": DegradeReason.TIMEOUT,
    "UPSTREAM": DegradeReason.UPSTREAM,
    "CANCELLED": DegradeReason.CANCELLED,
}

#: 降级时写进 `quality_notes`、并在没有部分结果时作为回答正文的可见说明（R7）。
_DEGRADE_NOTES: Final[dict[DegradeReason, dict[SupportedLocale, str]]] = {
    DegradeReason.LIMIT: {
        SupportedLocale.ZH_CN: "已达到本次处理的步骤上限，以下仅为已获得的部分结果。",
        SupportedLocale.EN_US: (
            "This request reached its step limit; only partial results are shown."
        ),
    },
    DegradeReason.TIMEOUT: {
        SupportedLocale.ZH_CN: "处理时间已达上限，以下仅为已获得的部分结果。",
        SupportedLocale.EN_US: "This request ran out of time; only partial results are shown.",
    },
    DegradeReason.BUDGET: {
        SupportedLocale.ZH_CN: "本次请求的模型预算已达上限，以下仅为已获得的部分结果。",
        SupportedLocale.EN_US: (
            "The model budget for this request is used up; only partial results are shown."
        ),
    },
    DegradeReason.UPSTREAM: {
        SupportedLocale.ZH_CN: "模型服务暂时不可用，本次未能完成回答。",
        SupportedLocale.EN_US: (
            "The model service is temporarily unavailable; no answer could be completed."
        ),
    },
    DegradeReason.CANCELLED: {
        SupportedLocale.ZH_CN: "连接已断开，本次处理已停止。",
        SupportedLocale.EN_US: "The connection was closed; processing stopped.",
    },
    DegradeReason.VALIDATION: {
        SupportedLocale.ZH_CN: "回答未通过校验，为避免给出未经核实的内容，本次不展示模型回答。",
        SupportedLocale.EN_US: (
            "The answer failed validation and is withheld to avoid unverified content."
        ),
    },
}

_DAILY_BUDGET_NOTES: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: "每日模型费用预算已用尽，本次未能完成回答。",
    SupportedLocale.EN_US: (
        "The daily model budget is exhausted; this answer could not be completed."
    ),
}

_REVISE_PROMPT: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: (
        "上面的回答未通过校验：{issues}。请只依据已有的工具结果重写回答，不要编造数字。"
    ),
    SupportedLocale.EN_US: (
        "The answer above failed validation: {issues}. Rewrite it using only the tool results "
        "already provided, without inventing numbers."
    ),
}

_SKILL_LIMIT_SUMMARY: Final = (
    "本回合加载的 Skill 已达上限 {limit} 个，这次没有加载；请依据已加载的 Skill 与工具结果继续。"
)

_REVIEW_FALLBACK_NOTE: Final[dict[SupportedLocale, str]] = {
    SupportedLocale.ZH_CN: "独立复核未通过",
    SupportedLocale.EN_US: "The independent review did not pass",
}

#: DeepSeek 内部工具调用标记（半角或全角竖线，如 `<｜｜DSML｜｜ calls>`）。
#: 2026-09-30 E5 真实对比中，不给工具时模型把这段语法直接写进了正文。
_TOOL_CALL_MARKUP: Final = re.compile(r"<\s*/?\s*[|｜]+\s*DSML\s*[|｜]+")


# --- 输入输出 --------------------------------------------------------------------


@dataclass(frozen=True)
class LoopRequest:
    context: ToolContext
    system_prompt: str
    user_message: str
    history: Sequence[LlmMessage] = ()
    locale: SupportedLocale = SupportedLocale.ZH_CN
    #: 按用户变化的记忆段（调用方已围栏）。模型看得到，但**不是数字来源**（M11、A6）：
    #: 与 `system_prompt` 分开传，确定性校验只把后者算作来源；放在稳定前缀之后（A9）。
    memory_context: str = ""


@dataclass
class LoopOutcome:
    answer: str
    tool_calls: list[ToolDisplay]
    stop_reason: StopReason
    degraded: bool
    degraded_reason: DegradeReason | None
    quality_status: QualityStatus
    quality_attempts: int
    quality_notes: list[str]
    llm_calls: int
    #: 供后端确定性代码（来源、引用、图表）消费；`payload` 永不进 SSE，只有 `tool_calls` 可以。
    tool_results: list[ToolResult] = field(default_factory=list)
    #: 本回合经受信通道加载的 Skill 名（按加载顺序）与是否触及单回合上限。
    #: 只给后端与评测，不进 SSE、不进响应契约。
    loaded_skills: list[str] = field(default_factory=list)
    skill_limit_hit: bool = False
    #: 本回合每次实际生效的压缩所用策略（按发生顺序）；调用方据此写 `thinking_steps`。
    compactions: list[CompactionStrategy] = field(default_factory=list)


@dataclass(frozen=True)
class ToolCallStarted:
    """一次工具调用开始（在闸门之前发出）；路由用 `started_display()` 投影成 `tool_call` 事件。"""

    tool_name: str
    call_id: str


@dataclass(frozen=True)
class ToolCallFinished:
    """一次工具调用结束；路由用 `display.result_event(locale)` 投影成 `tool_result` 事件。"""

    display: ToolDisplay


@dataclass(frozen=True)
class ContextCompacted:
    """一次压缩改变了模型可见的上下文；路由投影成 `step` 事件。只含策略，不含任何上下文内容。"""

    strategy: CompactionStrategy


LoopEvent = ToolCallStarted | ToolCallFinished | ContextCompacted
#: 循环进行中的事件出口，供 SSE 在回合结束前逐步推送；事件里只有 `ToolDisplay` 级别的信息。
EventSink = Callable[[LoopEvent], Awaitable[None]]


@dataclass(frozen=True)
class ReviewVerdict:
    passed: bool
    notes: tuple[str, ...] = ()


class Reviewer(Protocol):
    """独立 Reviewer：每次复核在同一份 `budget` 上扣一次调用。"""

    async def review(
        self, *, answer: str, evidence: Sequence[ToolResult], budget: LlmBudget
    ) -> ReviewVerdict: ...


# --- 主循环 ----------------------------------------------------------------------


class _Stop(Exception):
    def __init__(self, reason: StopReason) -> None:
        super().__init__(reason)
        self.reason = reason


async def run_loop(
    request: LoopRequest,
    *,
    llm: ConversationalLlmClient,
    gates: ToolGates,
    tools: Sequence[ToolSchema],
    limits: LoopLimits,
    checks: Sequence[DeterministicCheck] = DEFAULT_CHECKS,
    reviewer: Reviewer | None = None,
    cancel: asyncio.Event | None = None,
    on_event: EventSink | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> LoopOutcome:
    """跑完一个回合。致命错误（`FatalToolError`）原样抛出，其余结局都是 `LoopOutcome`。

    致命错误抛出前会带上本回合已完成的工具调用（`completed_tool_calls`）与已发生的 LLM 调用数，
    路由层据此把已完成的部分落库（§6.10）；它们只含 `ToolDisplay`，不含 payload。
    """

    run = _Run(request, llm, gates, list(tools), limits, cancel, on_event, clock)
    try:
        answer = await run.tool_loop()
        return await run.quality(answer, checks, reviewer)
    except _Stop as stop:
        return run.stopped(stop.reason)
    except FatalToolError as fatal:
        fatal.completed_tool_calls = tuple(run.displays)
        fatal.llm_calls = run.budget.calls
        raise


class _Run:
    def __init__(
        self,
        request: LoopRequest,
        llm: ConversationalLlmClient,
        gates: ToolGates,
        tools: list[ToolSchema],
        limits: LoopLimits,
        cancel: asyncio.Event | None,
        on_event: EventSink | None,
        clock: Callable[[], float],
    ) -> None:
        self.request = request
        self.llm = llm
        self.gates = gates
        self.tools = tools
        self.limits = limits
        self.cancel = cancel
        self.on_event = on_event
        self.clock = clock
        self.deadline = clock() + limits.wall_clock_seconds
        self.budget = limits.new_budget()
        self.messages = _initial_messages(request)
        #: 回答里的数字可以引用的非工具来源：系统提示词（店名等）、本轮与历史中的**用户**消息。
        #: 历史里的助手回答是模型生成内容，不能给本轮数字作证（D-N4-1，契约 §6.12）——
        #: 否则模型复述一次自己编的数字，下一轮就能凭「历史」通过校验。
        self.sources = [
            request.system_prompt,
            request.user_message,
            *(m.content for m in request.history if m.role == "user"),
        ]
        self.displays: list[ToolDisplay] = []
        self.results: list[ToolResult] = []
        self.tool_count = 0
        self.quality_attempts = 0
        self.quality_notes: list[str] = []
        self.daily_budget_exhausted = False
        self.skill_loads = 0
        self.loaded_skills: list[str] = []
        self.skill_limit_hit = False
        self.compactions: list[CompactionStrategy] = []
        self.compaction_calls = 0

    # --- 工具轮 ------------------------------------------------------------------

    async def tool_loop(self) -> str:
        for turn_number in range(1, self.limits.max_turns + 1):
            await self.maybe_compact()
            turn = await self.converse(self.tools)
            if turn.stop_reason == "END_TURN":
                if not (turn.text or "").strip():
                    # 推理耗尽 token 时上游常返回空正文：这不是「答完了」，是没答出来（R7）。
                    raise _Stop("UPSTREAM")
                return turn.text or ""
            if turn.stop_reason == "MAX_TOKENS":
                raise _Stop("BUDGET")
            self.messages.append(
                LlmMessage(
                    role="assistant",
                    content=turn.text or "",
                    tool_calls=list(turn.tool_calls),
                    reasoning=turn.reasoning,
                )
            )
            if turn_number == self.limits.max_turns:
                # 没有下一轮来消费这批工具的结果，执行它们只剩副作用。
                raise _Stop("MAX_TURNS")
            if self.tool_count + len(turn.tool_calls) > self.limits.max_tool_calls:
                raise _Stop("MAX_TOOL_CALLS")
            await self.run_batch(turn.tool_calls)
        raise _Stop("MAX_TURNS")  # pragma: no cover - 循环体已覆盖所有出口

    async def maybe_compact(self) -> None:
        policy = self.limits.compaction
        if policy is None or estimate_tokens(self.messages) <= policy.trigger_tokens:
            return
        locale = self.request.locale
        outcome: CompactionOutcome
        if policy.strategy is CompactionStrategy.SUMMARIZATION:
            outcome = await self.guard(
                summarize_early_context(
                    self.messages,
                    self.results,
                    llm=self.llm,
                    budget=self.budget,
                    locale=locale,
                    remaining_calls=policy.max_calls - self.compaction_calls,
                    keep_recent_rounds=policy.keep_recent_rounds,
                )
            )
        else:
            outcome = prune_tool_results(
                self.messages,
                self.results,
                locale=locale,
                keep_recent_rounds=policy.keep_recent_rounds,
            )
        self.compaction_calls += outcome.llm_calls
        if not outcome.changed:
            return
        self.messages = outcome.messages
        self.compactions.append(outcome.strategy_used)
        await self.emit(ContextCompacted(strategy=outcome.strategy_used))

    async def converse(self, tools: list[ToolSchema]) -> LlmTurn:
        try:
            turn = await self.guard(
                self.llm.converse(messages=list(self.messages), tools=tools, budget=self.budget)
            )
        except LlmDailyBudgetExceededError:
            self.daily_budget_exhausted = True
            raise _Stop("BUDGET") from None
        except LlmBudgetError:
            raise _Stop("BUDGET") from None
        except LlmUnavailableError:
            raise _Stop("UPSTREAM") from None
        if turn.degraded or turn.stop_reason == "ERROR":
            raise _Stop("UPSTREAM")
        if turn.text and _TOOL_CALL_MARKUP.search(turn.text):
            # 上游把内部工具调用语法写进了正文（常见于不给工具的质量重写）：这不是回答，
            # 不能原样展示给用户，也不能当成工具调用执行（R7：按上游异常可见降级）。
            logger.warning(
                "tool_call_markup_in_text request_id=%s", self.request.context.request_id
            )
            raise _Stop("UPSTREAM")
        return turn

    async def run_batch(self, calls: Sequence[LlmToolCall]) -> None:
        ctx = self.request.context
        # 上游 ID 会进入 SSE 与最终响应；整批先校验，避免先发事件或执行部分工具。
        if any(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", c.call_id) is None for c in calls):
            raise _Stop("UPSTREAM")
        # 先让整批调用全部过闸门，再执行其中任何一个：致命闸门在任何副作用之前生效。
        for c in calls:
            await self.emit(ToolCallStarted(tool_name=c.tool_name, call_id=c.call_id))
        admitted: list[AdmittedCall | ToolResult] = [
            await self.guard(
                self.gates.admit(ctx, c.tool_name, c.arguments_json, call_id=c.call_id)
            )
            for c in calls
        ]
        admitted = [self.limit_skill_load(item) for item in admitted]
        runnable = [a for a in admitted if isinstance(a, AdmittedCall)]
        executed: dict[int, ToolResult] = {}
        if len(runnable) > 1 and all(_parallel_safe(a) for a in runnable):
            outcomes = await self.guard(
                asyncio.gather(
                    *(self.gates.execute(ctx, a) for a in runnable), return_exceptions=True
                )
            )
            for call_, outcome in zip(runnable, outcomes, strict=True):
                if isinstance(outcome, BaseException):
                    raise outcome
                executed[id(call_)] = outcome
        for tool_call, item in zip(calls, admitted, strict=True):
            if isinstance(item, ToolResult):
                result = item
            elif id(item) in executed:
                result = executed[id(item)]
            else:
                result = await self.guard(
                    self.gates.execute(ctx, item), interruptible=_parallel_safe(item)
                )
            # 串行写每完成一项立即记录，下一项取消不能抹去已经生效的结果。
            self.tool_count += 1
            self.results.append(result)
            self.displays.append(result.display)
            await self.emit(ToolCallFinished(display=result.display))
            self.messages.append(
                LlmMessage(
                    role="tool",
                    content=self.tool_content(tool_call.tool_name, result),
                    tool_call_id=tool_call.call_id,
                )
            )

    def limit_skill_load(self, item: AdmittedCall | ToolResult) -> AdmittedCall | ToolResult:
        """单回合 `load_skill` 计数；超限的调用不执行，换成交还模型的拒绝结果（不静默忽略）。"""

        if not isinstance(item, AdmittedCall) or item.spec.name != LOAD_SKILL_TOOL:
            return item
        self.skill_loads += 1
        if self.skill_loads <= self.limits.max_skill_loads:
            return item
        self.skill_limit_hit = True
        logger.warning(
            "skill_load_limit_hit limit=%s request_id=%s",
            self.limits.max_skill_loads,
            self.request.context.request_id,
        )
        return ToolResult(
            ok=False,
            payload=None,
            display=ToolDisplay(
                tool_name=LOAD_SKILL_TOOL,
                call_id=item.call_id,
                status=DISPLAY_STATUS[ToolOutcome.REJECTED],
                duration_ms=0,
                row_count=None,
            ),
            reason_code=ErrorCode.INVALID_REQUEST,
            outcome=ToolOutcome.REJECTED,
            summary=_SKILL_LIMIT_SUMMARY.format(limit=self.limits.max_skill_loads),
        )

    def tool_content(self, tool_name: str, result: ToolResult) -> str:
        """受信 Skill 原样进上下文；其余一切（含伪造 `<skill>` 标记的文本）照常围栏。"""

        payload = result.payload
        if (
            tool_name == LOAD_SKILL_TOOL
            and result.ok
            and isinstance(payload, SkillSpec)
            and tool_role_for(self.request.context.session.role) in payload.roles
        ):
            self.loaded_skills.append(payload.name)
            return render_skill_message(payload)
        return fence(_tool_message(result), source=f"tool:{tool_name}")

    # --- 质量 --------------------------------------------------------------------

    async def quality(
        self, answer: str, checks: Sequence[DeterministicCheck], reviewer: Reviewer | None
    ) -> LoopOutcome:
        locale = self.request.locale
        while True:
            self.quality_attempts += 1
            # 确定性校验在前：它不通过时，根本不调用 LLM Reviewer（Q16，安全不依赖 Reviewer）。
            issues = [
                issue
                for check in checks
                for issue in check(answer, self.results, sources=self.sources, locale=locale)
            ]
            reviewed = False
            if not issues and reviewer is not None:
                verdict = await self.review(reviewer, answer)
                reviewed = True
                if not verdict.passed:
                    issues = list(verdict.notes) or [_REVIEW_FALLBACK_NOTE[locale]]
            if not issues:
                return self.outcome(
                    answer,
                    "COMPLETED",
                    None,
                    QualityStatus.PASSED if reviewed else QualityStatus.NOT_RUN,
                )
            self.quality_notes.extend(issues)
            if self.quality_attempts >= self.limits.quality_max_attempts:
                note = _DEGRADE_NOTES[DegradeReason.VALIDATION][locale]
                self.quality_notes.append(note)
                return self.outcome(
                    note, "COMPLETED", DegradeReason.VALIDATION, QualityStatus.DEGRADED
                )
            answer = await self.regenerate(answer, issues)

    async def review(self, reviewer: Reviewer, answer: str) -> ReviewVerdict:
        try:
            return await self.guard(
                reviewer.review(answer=answer, evidence=tuple(self.results), budget=self.budget)
            )
        except LlmDailyBudgetExceededError:
            self.daily_budget_exhausted = True
            raise _Stop("BUDGET") from None
        except LlmBudgetError:
            raise _Stop("BUDGET") from None
        except LlmUnavailableError:
            raise _Stop("UPSTREAM") from None

    async def regenerate(self, answer: str, issues: list[str]) -> str:
        separator = "；" if self.request.locale is SupportedLocale.ZH_CN else "; "
        self.messages.append(LlmMessage(role="assistant", content=answer))
        self.messages.append(
            LlmMessage(
                role="user",
                content=_REVISE_PROMPT[self.request.locale].format(issues=separator.join(issues)),
            )
        )
        # 重新生成不给工具：只能依据已有证据改写，不能借机再去取数或写入。
        turn = await self.converse([])
        if turn.stop_reason == "MAX_TOKENS":
            raise _Stop("BUDGET")
        if not (turn.text or "").strip():
            raise _Stop("UPSTREAM")
        return turn.text or ""

    # --- 结局 --------------------------------------------------------------------

    def stopped(self, reason: StopReason) -> LoopOutcome:
        degrade = _STOP_DEGRADE[reason]
        note = (
            _DAILY_BUDGET_NOTES[self.request.locale]
            if reason == "BUDGET" and self.daily_budget_exhausted
            else _DEGRADE_NOTES[degrade][self.request.locale]
        )
        self.quality_notes.append(note)
        status = QualityStatus.DEGRADED if self.quality_attempts else QualityStatus.NOT_RUN
        # 非 END_TURN 的模型正文尚未经过确定性校验，可能包含虚构金额或越权承诺。
        # 已完成工具调用仍通过 tool_calls/tool_results 单独保留供调用方落库。
        return self.outcome(note, reason, degrade, status)

    def outcome(
        self,
        answer: str,
        reason: StopReason,
        degrade: DegradeReason | None,
        status: QualityStatus,
    ) -> LoopOutcome:
        return LoopOutcome(
            answer=answer,
            tool_calls=list(self.displays),
            stop_reason=reason,
            degraded=degrade is not None,
            degraded_reason=degrade,
            quality_status=status,
            quality_attempts=self.quality_attempts,
            quality_notes=list(self.quality_notes),
            llm_calls=self.budget.calls,
            tool_results=list(self.results),
            loaded_skills=list(self.loaded_skills),
            skill_limit_hit=self.skill_limit_hit,
            compactions=list(self.compactions),
        )

    async def emit(self, event: LoopEvent) -> None:
        if self.on_event is not None:
            await self.on_event(event)

    # --- 墙钟与取消 ----------------------------------------------------------------

    def check_live(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise _Stop("CANCELLED")
        if self.clock() >= self.deadline:
            raise _Stop("WALL_CLOCK")

    async def guard[T](self, awaitable: Awaitable[T], *, interruptible: bool = True) -> T:
        """在墙钟与断开信号的约束下等待一个步骤。

        `interruptible=False` 用于写操作：开始前照常检查，开始后等它做完，结束后由下一步的
        `check_live()` 再停止。
        """

        try:
            self.check_live()
        except _Stop:
            # 这一步不再开始：协程直接关闭；gather 之类的 Future 已排好子任务，取消它们，
            # 否则被放弃的只读工具仍会在后台跑完，结果无人消费。
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            elif isinstance(awaitable, asyncio.Future):
                awaitable.cancel()
                awaitable.add_done_callback(_consume_outcome)
            raise
        task = asyncio.ensure_future(awaitable)
        if not interruptible:
            return await task
        waiters: set[asyncio.Future[object]] = {task}  # type: ignore[arg-type]
        cancel_waiter = (
            asyncio.ensure_future(self.cancel.wait()) if self.cancel is not None else None
        )
        if cancel_waiter is not None:
            waiters.add(cancel_waiter)  # type: ignore[arg-type]
        try:
            done, _ = await asyncio.wait(
                waiters,
                timeout=max(0.0, self.deadline - self.clock()),
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise
        finally:
            if cancel_waiter is not None:
                cancel_waiter.cancel()
                with suppress(asyncio.CancelledError):
                    await cancel_waiter
        if task in done:
            return task.result()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        raise _Stop(
            "CANCELLED" if self.cancel is not None and self.cancel.is_set() else "WALL_CLOCK"
        )


def _consume_outcome(future: asyncio.Future[object]) -> None:
    """被放弃的 gather 以 CancelledError 收尾；取走它，免得报「exception never retrieved」。"""

    if not future.cancelled():
        future.exception()


def _parallel_safe(call: AdmittedCall) -> bool:
    return call.spec.write_policy is WritePolicy.READ_ONLY and call.spec.parallelizable


def _initial_messages(request: LoopRequest) -> list[LlmMessage]:
    customer = request.context.session.role is SessionRole.CUSTOMER
    system = f"{request.system_prompt}\n\n{FENCE_POLICY}"
    if request.memory_context:
        system = f"{system}\n\n{request.memory_context}"
    messages = [LlmMessage(role="system", content=system)]
    for message in request.history:
        if customer and message.role == "user":
            message = LlmMessage(role="user", content=fence(message.content, source="customer"))
        messages.append(message)
    content = request.user_message
    # 顾客输入属于 A11 的外部文本；商家是店铺经营者本人，其指令就是任务本身。
    messages.append(
        LlmMessage(role="user", content=fence(content, source="customer") if customer else content)
    )
    return messages


def _tool_message(result: ToolResult) -> str:
    guardrail = result.guardrail
    return json.dumps(
        {
            "ok": result.ok,
            "outcome": result.outcome.value,
            "reason_code": result.reason_code.value if result.reason_code else None,
            "summary": result.summary,
            "guardrail": guardrail.model_dump(mode="json") if guardrail else None,
            "data": result.payload,
        },
        ensure_ascii=False,
        default=str,
    )
