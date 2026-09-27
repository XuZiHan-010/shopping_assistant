"""N2 Task 5：新工具循环与冻结 LangGraph 基线在共有旧能力上的结构对照（§5.6、PRD A2）。

**全程 Fake LLM，零费用。** 两条路径拿到的是同一份脚本化模型输出与同一个受控查询替身，
所以这份对照**只能证明结构正确**——调用次数、降级路径、代码断言是否成立——
**不能证明回答质量更好或更差**。真实模型对照是 N1 评测计划 Task 7 步骤 3，另需 R3 授权。

- 基线侧：真实的 `MerchantQaGraph`（未改动），意图 / 回答 / 复核三个 LLM 口子
  都接同一个 `FakeLlmClient`；
- 新循环侧：真实的 `run_loop()` + `ToolGates`，挂一个**仅供本对照使用**的 `query_metric` 只读工具，
  它调用与基线同一个查询替身。它不是业务工具，不注册进生产注册表；
- 只比双方共有的旧能力：从 `app/eval/datasets/quality/` 按 `skill` 过滤。

复现::

    cd backend
    # 重写 docs/history/eval/n2-baseline-comparison.md
    uv run python -m tests.eval.baseline_comparison

`tests/eval/test_baseline_comparison.py` 断言已提交的报告与重新生成的结果逐字一致。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.agent.graph import MerchantQaGraph
from app.agent.loop.limits import LoopLimits
from app.agent.loop.runner import LoopRequest, ReviewVerdict, run_loop
from app.core.session import SessionContext, SessionRole
from app.eval.cases import AssertionType, EvalCase, load_cases_from_directory
from app.knowledge.retrieval import KnowledgeRetrieval
from app.llm.client import LlmBudget, LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient
from app.localization.locales import SupportedLocale
from app.metrics.catalog import MetricCatalog
from app.repositories.analytics import ResultColumn
from app.services.safe_query import QueryResult
from app.tools.gates import ProvenanceScope, ToolGates
from app.tools.registry import ToolRegistry
from app.tools.types import (
    ObjectRef,
    ToolContext,
    ToolOutput,
    ToolResult,
    ToolRole,
    ToolSpec,
    WritePolicy,
)

_BACKEND = Path(__file__).resolve().parents[2]
QUALITY_DIR = _BACKEND / "app" / "eval" / "datasets" / "quality"
REPORT_PATH = _BACKEND.parent / "docs" / "history" / "eval" / "n2-baseline-comparison.md"

#: 双方共有的旧能力（A2）。计划列了指标、规则、闲聊、拒答四类，但 N1 质量集只有前后两类里的
#: 指标与闲聊；规则与拒答没有用例，报告里如实写明未覆盖。
SHARED_SKILLS = ("chat_metric", "chat_greeting")

MERCHANT_ID = UUID("00000000-0000-4000-8000-000000000100")
_SESSION_RECORD_ID = UUID("00000000-0000-4000-8000-00000000c0de")
_QUERY_DATE = date(2026, 8, 3)

_ANSWER: Mapping[SupportedLocale, str] = {
    SupportedLocale.ZH_CN: "今天成交 GMV 为 1200.00 元。",
    SupportedLocale.EN_US: "Today's GMV is 1200.00.",
}
_GREETING: Mapping[SupportedLocale, str] = {
    SupportedLocale.ZH_CN: "你好，我是 Borough 经营助手。",
    SupportedLocale.EN_US: "Hello, I am the Borough business assistant.",
}


# --- 两条路径共用的受控查询替身 -----------------------------------------------------


class SharedQueryStub:
    """两条路径都从这里取数：比较的是编排结构，不是数据来源。"""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self, context: object, intent: object, *, now: object, keywords: Sequence[str] = ()
    ) -> QueryResult:
        del context, intent, now, keywords
        self.calls += 1
        return QueryResult(
            columns=(
                ResultColumn("date", "日期", "DIMENSION"),
                ResultColumn("gmv", "成交 GMV", "METRIC"),
            ),
            rows=[{"date": _QUERY_DATE, "gmv": Decimal("1200.00")}],
            total_rows=1,
            truncated=False,
            source_tables=("orders",),
            plan_steps=("按商家范围检索成交 GMV",),
            export_spec=None,
            notes=(),
            non_additive=False,
        )


# --- 基线侧脚本 -------------------------------------------------------------------


def _intent(mode: str, keywords: list[str]) -> str:
    category = "TRADE" if mode == "METRIC" else "UNKNOWN"
    return json.dumps({"answer_mode": mode, "category": category, "intent_keywords": keywords})


def _understand(mode: str) -> str:
    metric = mode == "METRIC"
    return json.dumps(
        {
            "answer_mode": mode,
            "category": "TRADE" if metric else "UNKNOWN",
            "metric": "gmv" if metric else None,
            "dimensions": ["date"] if metric else [],
            "filters": {},
            "date_range": {"start": _QUERY_DATE.isoformat(), "end": _QUERY_DATE.isoformat()}
            if metric
            else None,
            "sort": None,
            "limit": None,
            "followup_reference": False,
            "needs_attachment": False,
        }
    )


def _answer_draft(locale: SupportedLocale) -> str:
    evidence = "GMV 1200.00"
    return json.dumps(
        {
            "answer": _ANSWER[locale],
            "recommendations": [
                {"title": "关注成交", "evidence": evidence, "action": "对比昨日"},
                {"title": "关注客单", "evidence": evidence, "action": "查看订单数"},
            ],
        },
        ensure_ascii=False,
    )


_REVIEW_PASS = json.dumps({"passed": True, "issues": [], "advisory_notes": []})


def _baseline_script(skill: str, locale: SupportedLocale) -> list[str]:
    if skill == "chat_metric":
        return [
            _intent("METRIC", ["销售额"]),
            _understand("METRIC"),
            _answer_draft(locale),
            _REVIEW_PASS,
        ]
    return [_intent("CHAT", []), _understand("CHAT")]


class _NoDocuments:
    async def list_active(self) -> list[object]:
        return []


class _NoMetricDefinition:
    async def get_by_code(self, metric_code: str) -> None:
        del metric_code


# --- 新循环侧：仅供本对照使用的指标工具 ----------------------------------------------


class MetricQueryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_code: str


_ACTIVE_STUB: SharedQueryStub | None = None


async def query_metric(ctx: ToolContext, args: MetricQueryArgs) -> ToolOutput:
    assert _ACTIVE_STUB is not None
    result = await _ACTIVE_STUB.execute(ctx, args, now=None)
    return ToolOutput(
        payload={
            "metric_code": args.metric_code,
            "rows": [dict(row) for row in result.rows],
            "source_tables": list(result.source_tables),
        },
        summary="已查询指标",
        row_count=result.total_rows,
    )


async def _metric_options(ctx: ToolContext) -> Mapping[str, frozenset[str]]:
    del ctx
    return {"metric_code": frozenset({"gmv"})}


COMPARISON_METRIC_TOOL = ToolSpec(
    name="query_metric",
    roles=frozenset({ToolRole.MERCHANT}),
    args_model=MetricQueryArgs,
    write_policy=WritePolicy.READ_ONLY,
    parallelizable=True,
    description="按指标机器码查询当前商家的经营指标（仅供基线对照）",
    executor=query_metric,
    option_source=_metric_options,
)


class _MemoryProvenance:
    def __init__(self) -> None:
        self.seen: set[tuple[ProvenanceScope, ObjectRef]] = set()

    async def has(self, scope: ProvenanceScope, ref: ObjectRef) -> bool:
        return (scope, ref) in self.seen

    async def record(self, scope: ProvenanceScope, refs: Sequence[ObjectRef]) -> None:
        self.seen.update((scope, ref) for ref in refs)


class _NoAudit:
    async def record_tool_block(self, ctx: ToolContext, *, tool_name: str, gate: str) -> None:
        raise AssertionError(f"对照用例不应触发安全闸门：{tool_name}/{gate}")


class _PassingReviewer:
    """与基线同样只对指标回答做一次独立复核，并同样扣一次 LLM 调用。"""

    async def review(
        self, *, answer: str, evidence: Sequence[ToolResult], budget: LlmBudget
    ) -> ReviewVerdict:
        del answer, evidence
        budget.charge_call()
        return ReviewVerdict(passed=True)


def _loop_script(skill: str, locale: SupportedLocale) -> list[LlmTurn]:
    if skill == "chat_metric":
        call = LlmToolCall(
            call_id="call_metric", tool_name="query_metric", arguments_json='{"metric_code": "gmv"}'
        )
        return [
            LlmTurn(text=None, tool_calls=[call], stop_reason="TOOL_USE", tokens=10),
            LlmTurn(text=_ANSWER[locale], tool_calls=[], stop_reason="END_TURN", tokens=10),
        ]
    return [LlmTurn(text=_GREETING[locale], tool_calls=[], stop_reason="END_TURN", tokens=10)]


# --- 执行与断言 -------------------------------------------------------------------


@dataclass(frozen=True)
class PathResult:
    case_id: str
    skill: str
    locale: str
    completed: bool
    degraded: bool
    quality_status: str
    llm_calls: int
    query_calls: int
    assertions_passed: int
    assertions_applicable: int


def _message(case: EvalCase) -> str:
    request = case.turns[0].request
    assert request is not None and request.json_body is not None
    return str(request.json_body["message"])


def _check_assertions(case: EvalCase, observed: Mapping[str, Any]) -> tuple[int, int]:
    """按用例原有代码断言逐条核对；新循环没有对应字段的断言记为不适用，不算通过也不算失败。"""

    passed = applicable = 0
    for assertion in case.assertions:
        if assertion.type is AssertionType.HTTP_STATUS:
            key = "http_status"
        elif assertion.type is AssertionType.RESPONSE_FIELD and assertion.path is not None:
            key = assertion.path
        else:
            continue
        if key not in observed:
            continue
        applicable += 1
        passed += int(observed[key] == assertion.expected)
    return passed, applicable


async def run_baseline(case: EvalCase) -> PathResult:
    locale = SupportedLocale(case.locale)
    llm = FakeLlmClient(responses=_baseline_script(case.skill, locale))
    stub = SharedQueryStub()
    graph = MerchantQaGraph(
        retrieval=KnowledgeRetrieval(_NoDocuments()),  # type: ignore[arg-type]
        intent_service_llm=llm,
        catalog=MetricCatalog(_NoMetricDefinition(), llm),  # type: ignore[arg-type]
        query_service=stub,
        merchant_id=MERCHANT_ID,
        answer_llm=llm,
        reviewer_llm=llm,
        quality_max_attempts=2,
        max_llm_calls=10,  # 与 v1 生产上限 MAX_LLM_CALLS_PER_REQUEST 一致
    )
    result = await graph.run(_message(case), _SESSION_RECORD_ID, locale=locale)
    response = result.response
    observed = {
        "http_status": 200,
        "answer_mode": response.answer_mode.value,
        "degraded": response.degraded,
    }
    passed, applicable = _check_assertions(case, observed)
    return PathResult(
        case.id,
        case.skill,
        case.locale,
        completed=True,
        degraded=response.degraded,
        quality_status=response.quality_status.value,
        llm_calls=len(llm.calls),
        query_calls=stub.calls,
        assertions_passed=passed,
        assertions_applicable=applicable,
    )


async def run_new_loop(case: EvalCase) -> PathResult:
    global _ACTIVE_STUB
    locale = SupportedLocale(case.locale)
    stub = SharedQueryStub()
    _ACTIVE_STUB = stub
    registry = ToolRegistry()
    registry.register(COMPARISON_METRIC_TOOL)
    gates = ToolGates(
        registry,
        provenance=_MemoryProvenance(),
        principal_secret=b"baseline-comparison-principal-secret",
        audit=_NoAudit(),
    )
    session = SessionContext(_SESSION_RECORD_ID, SessionRole.MERCHANT, MERCHANT_ID, None, None)
    llm = FakeLlmClient(turns=_loop_script(case.skill, locale))
    outcome = await run_loop(
        LoopRequest(
            context=ToolContext(session=session, conversation_id=case.id, request_id=case.id),
            system_prompt="你是 Borough 商家经营助手。",
            user_message=_message(case),
            locale=locale,
        ),
        llm=llm,
        gates=gates,
        tools=registry.schemas_for(SessionRole.MERCHANT),
        limits=LoopLimits(
            max_turns=8,
            max_tool_calls=16,
            max_llm_calls=12,
            wall_clock_seconds=30.0,
            max_tokens=25_000,
            quality_max_attempts=2,
        ),
        reviewer=_PassingReviewer() if case.skill == "chat_metric" else None,
    )
    # v2 是否暴露 answer_mode 由 N1 字段契约决定，新循环不产生它，对应断言记为不适用。
    observed = {"http_status": 200, "degraded": outcome.degraded}
    passed, applicable = _check_assertions(case, observed)
    return PathResult(
        case.id,
        case.skill,
        case.locale,
        completed=outcome.stop_reason == "COMPLETED",
        degraded=outcome.degraded,
        quality_status=outcome.quality_status.value,
        llm_calls=outcome.llm_calls,
        query_calls=stub.calls,
        assertions_passed=passed,
        assertions_applicable=applicable,
    )


def shared_cases() -> list[EvalCase]:
    return [c for c in load_cases_from_directory(QUALITY_DIR) if c.skill in SHARED_SKILLS]


async def compare() -> list[tuple[PathResult, PathResult]]:
    return [(await run_baseline(case), await run_new_loop(case)) for case in shared_cases()]


# --- 报告 ------------------------------------------------------------------------

DISCLAIMER = (
    "**本对照只证明结构正确，不证明回答质量。** 两条路径使用同一份脚本化 Fake LLM 输出与同一个"
    "受控查询替身，回答正文由脚本决定；调用次数、降级路径与代码断言的差异反映编排结构，"
    "**不得据此宣称新循环质量优于或劣于基线**。真实模型对照属 N1 评测计划 Task 7 步骤 3，"
    "须按 R3 另行授权，当前状态：待人工验收。"
)


def _rate(numerator: int, denominator: int) -> str:
    return "—" if denominator == 0 else f"{numerator}/{denominator}"


def _summary(results: Sequence[PathResult]) -> list[str]:
    passed = sum(r.assertions_passed for r in results)
    applicable = sum(r.assertions_applicable for r in results)
    return [
        _rate(passed, applicable),
        _rate(sum(r.degraded for r in results), len(results)),
        _rate(sum(r.completed for r in results), len(results)),
        str(sum(r.llm_calls for r in results)),
        str(sum(r.query_calls for r in results)),
    ]


def render_report(pairs: Sequence[tuple[PathResult, PathResult]]) -> str:
    baseline = [b for b, _ in pairs]
    loop = [n for _, n in pairs]
    lines = [
        "# N2 新工具循环与冻结基线结构对照（Fake LLM）",
        "",
        "> 生成方式：`cd backend; uv run python -m tests.eval.baseline_comparison`；",
        "> 可复现性由 `tests/eval/test_baseline_comparison.py` 断言"
        "（重新生成须与本文件逐字一致）。",
        "> 计划：`plans/2026-09-21-n2-tool-loop-and-registry.md` Task 5。零费用，无真实模型调用。",
        "",
        DISCLAIMER,
        "",
        "## 范围",
        "",
        f"- 用例：`app/eval/datasets/quality/` 中 `skill ∈ {{{', '.join(SHARED_SKILLS)}}}` 的 "
        f"{len(pairs)} 条（双方共有的旧能力，A2）；",
        "- **未覆盖**：规则问答与拒答。N1 质量集没有这两类用例，"
        "新循环也还没有知识检索工具（N3/N4）；",
        "- 基线侧：未改动的 `MerchantQaGraph`，零 LLM 前置闸门关闭（受控查询替身之外没有知识库，"
        "开启会把指标题当作无关问题拒答，与本对照无关）；",
        "- 新循环侧：`run_loop()` + `ToolGates`，挂一个仅供本对照的只读 `query_metric` 工具，"
        "与基线调用同一个查询替身；指标回答与基线一样做一次独立复核；",
        "- 代码断言：沿用用例自带的 `http_status` / `response_field`；新循环不产生 `answer_mode`"
        "（v2 是否暴露由字段契约决定），该断言对新循环记为不适用。",
        "",
        "## 汇总",
        "",
        "| 路径 | 代码断言通过 | 降级 | 正常完成 | LLM 调用合计 | 受控查询合计 |",
        "| --- | --- | --- | --- | --- | --- |",
        "| 冻结基线 | " + " | ".join(_summary(baseline)) + " |",
        "| 新工具循环 | " + " | ".join(_summary(loop)) + " |",
        "",
        "## 逐条",
        "",
        "| 用例 | 能力 | 语言 | 基线 LLM | 循环 LLM | 基线查询 | 循环查询 | "
        "基线质量 | 循环质量 | 基线断言 | 循环断言 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for b, n in pairs:
        lines.append(
            f"| {b.case_id} | {b.skill} | {b.locale} | {b.llm_calls} | {n.llm_calls} | "
            f"{b.query_calls} | {n.query_calls} | {b.quality_status} | {n.quality_status} | "
            f"{_rate(b.assertions_passed, b.assertions_applicable)} | "
            f"{_rate(n.assertions_passed, n.assertions_applicable)} |"
        )
    lines += [
        "",
        "## 读法",
        "",
        "- LLM 调用差异来自编排结构：基线先「分类 + 理解」两次结构化调用再取数，"
        "新循环由一次决策调用"
        "直接发起工具调用、再由一次决策作答；两者都对指标回答做一次独立复核；",
        "- 闲聊：基线走分类 + 理解两次调用，新循环一次作答；两者质量状态都是 `NOT_RUN`（未复核）；",
        "- 这些数字只随编排结构或脚本变化；改动任一路径后重新生成本报告，测试会提示差异。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    pairs = asyncio.run(compare())
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(render_report(pairs), encoding="utf-8", newline="\n")
    print(f"已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
