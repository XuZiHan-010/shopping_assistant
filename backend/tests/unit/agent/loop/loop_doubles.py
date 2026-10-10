"""主循环单测的脚本回合、慢工具与 Reviewer 替身。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import count

from pydantic import BaseModel, ConfigDict

from app.agent.loop.limits import LoopLimits
from app.agent.loop.runner import LoopRequest, ReviewVerdict
from app.llm.client import LlmBudget, LlmToolCall, LlmTurn
from app.tools.errors import FatalToolError
from app.tools.gates import ToolGates
from app.tools.registry import ToolRegistry
from app.tools.types import ToolContext, ToolOutput, ToolResult, ToolRole, ToolSpec, WritePolicy
from tests.unit.tools.tool_doubles import (
    PRINCIPAL_SECRET,
    SPECS,
    InMemoryProvenance,
    RecordingAudit,
    RecordingDraftSink,
    ctx_for,
    customer_session,
    merchant_session,
)

SLOW_TOOL_SECONDS = 0.2
_ids = count(1)


class LabelArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


@dataclass
class ToolProbe:
    """记录慢工具的开始 / 结束，让并发与取消测试不依赖墙钟猜测。"""

    started: list[str] = field(default_factory=list)
    finished: list[str] = field(default_factory=list)
    first_started: asyncio.Event = field(default_factory=asyncio.Event)
    #: 同一时刻在跑的慢工具数与峰值：并行 / 串行直接看重叠，不靠墙钟阈值猜。
    active: int = 0
    max_active: int = 0

    def enter(self, label: str) -> None:
        self.started.append(label)
        self.first_started.set()
        self.active += 1
        self.max_active = max(self.max_active, self.active)

    def leave(self, label: str) -> None:
        self.active -= 1
        self.finished.append(label)


PROBE = ToolProbe()


async def slow_read(ctx: ToolContext, args: LabelArgs) -> ToolOutput:
    PROBE.enter(args.label)
    try:
        await asyncio.sleep(SLOW_TOOL_SECONDS)
    finally:
        PROBE.active -= 1
    PROBE.finished.append(args.label)
    return ToolOutput(payload={"label": args.label, "value": 4321}, summary="慢速读取")


BULK_TEXT = "规" * 2_500


async def bulk_read(ctx: ToolContext, args: LabelArgs) -> ToolOutput:
    """结果很长的只读工具（如规则检索）：用来把上下文撑过压缩阈值。"""

    return ToolOutput(payload={"label": args.label, "text": BULK_TEXT}, summary="长篇读取")


async def slow_write(ctx: ToolContext, args: LabelArgs) -> ToolOutput:
    PROBE.enter(args.label)
    await asyncio.sleep(SLOW_TOOL_SECONDS)
    PROBE.leave(args.label)
    return ToolOutput(payload={"label": args.label}, summary="慢速写入")


async def forbidden_read(ctx: ToolContext, args: LabelArgs) -> ToolOutput:
    """executor 自己的归属检查失败（例如订单不属于当前主体）：同样是致命错误。"""

    raise FatalToolError(gate="ownership", tool_name="forbidden_read", detail="不属于当前主体")


LOOP_SPECS = (
    *SPECS,
    ToolSpec(
        name="slow_read",
        roles=frozenset({ToolRole.CUSTOMER, ToolRole.MERCHANT}),
        args_model=LabelArgs,
        write_policy=WritePolicy.READ_ONLY,
        parallelizable=True,
        description="慢速只读工具",
        executor=slow_read,
    ),
    ToolSpec(
        name="bulk_read",
        roles=frozenset({ToolRole.CUSTOMER, ToolRole.MERCHANT}),
        args_model=LabelArgs,
        write_policy=WritePolicy.READ_ONLY,
        parallelizable=True,
        description="结果很长的只读工具",
        executor=bulk_read,
    ),
    ToolSpec(
        name="slow_write",
        roles=frozenset({ToolRole.CUSTOMER}),
        args_model=LabelArgs,
        write_policy=WritePolicy.CUSTOMER_DIRECT,
        parallelizable=False,
        description="慢速顾客直接写工具",
        executor=slow_write,
    ),
    ToolSpec(
        name="forbidden_read",
        roles=frozenset({ToolRole.CUSTOMER, ToolRole.MERCHANT}),
        args_model=LabelArgs,
        write_policy=WritePolicy.READ_ONLY,
        parallelizable=True,
        description="执行时发现越权的只读工具",
        executor=forbidden_read,
    ),
)


def build_gates() -> tuple[ToolGates, RecordingAudit]:
    registry = ToolRegistry()
    for spec in LOOP_SPECS:
        registry.register(spec)
    audit = RecordingAudit()
    gates = ToolGates(
        registry,
        provenance=InMemoryProvenance(),
        principal_secret=PRINCIPAL_SECRET,
        audit=audit,
        drafts=RecordingDraftSink(),
    )
    return gates, audit


# --- 脚本回合 ---------------------------------------------------------------------


def call(tool: str, **args: object) -> LlmToolCall:
    return LlmToolCall(
        call_id=f"call_{next(_ids)}", tool_name=tool, arguments_json=json.dumps(args)
    )


def tool_use_turn(*calls: LlmToolCall, tokens: int = 10) -> LlmTurn:
    if not calls:
        calls = (call("slow_read", label="x"),)
    return LlmTurn(text=None, tool_calls=list(calls), stop_reason="TOOL_USE", tokens=tokens)


def end_turn(text: str = "好的，已经为你整理好了。", *, tokens: int = 10) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=tokens)


def limits(**overrides: float) -> LoopLimits:
    values: dict[str, float] = {
        "max_turns": 8,
        "max_tool_calls": 16,
        "max_llm_calls": 12,
        "wall_clock_seconds": 10.0,
        "max_tokens": 10_000,
        "quality_max_attempts": 2,
    }
    values.update(overrides)
    return LoopLimits(**values)  # type: ignore[arg-type]


def customer_request(message: str = "帮我看看这款商品", conversation: str = "c1") -> LoopRequest:
    return LoopRequest(
        context=ctx_for(customer_session(), conversation),
        system_prompt="你是 Borough 店铺导购。",
        user_message=message,
    )


def merchant_request(message: str = "今天卖得怎么样") -> LoopRequest:
    return LoopRequest(
        context=ctx_for(merchant_session()),
        system_prompt="你是 Borough 商家经营助手。",
        user_message=message,
    )


# --- Reviewer 替身 ----------------------------------------------------------------


@dataclass
class ScriptedReviewer:
    """每次复核按真实 Reviewer 的方式扣一次 LLM 调用，按脚本给出结论。"""

    verdicts: list[bool] = field(default_factory=list)
    calls: int = 0

    async def review(
        self, *, answer: str, evidence: Sequence[ToolResult], budget: LlmBudget
    ) -> ReviewVerdict:
        budget.charge_call()
        self.calls += 1
        passed = self.verdicts.pop(0) if self.verdicts else True
        return ReviewVerdict(passed=passed, notes=() if passed else ("复核认为回答缺少依据",))
