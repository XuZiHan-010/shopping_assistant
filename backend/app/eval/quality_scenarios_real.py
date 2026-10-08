"""v2 质量场景（19 条）的真实模型复测；只在已获 R3 授权后显式 ``--real`` 执行。

与 `n5_quality_real` 跑的是同一批 v2 用例与同一条真实链路，区别在评分：
代码断言 → 叙述语言（确定性）→ 逐项判定裁判三票。裁判除了回答正文，还能看到
响应契约里的工具调用摘要，用来核对「说做了的动作是否真有对应调用」。
冻结基线的 6 条不在这里，它们由 `baseline_comparison_real` 负责。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.core.config import Settings
from app.db.session import Database
from app.eval.acceptance_evidence import (
    EvidenceBatch,
    append_evidence,
    prepare_output,
    validate_settings,
)
from app.eval.baseline_comparison_real import SideOutcome, verdict_row
from app.eval.cases import EvalCase
from app.eval.graders.assertions import evaluate_all
from app.eval.graders.criteria_judge import CriteriaRubric, Criterion, grade_by_criteria
from app.eval.n5_quality_real import (
    MeteredDeepSeek,
    _case_id,
    _execute_case,
    _seed,
    quality_cases,
)
from app.llm.deepseek import DeepSeekLlmClient
from app.main import create_app

_ASKS_FOR_SOURCE = re.compile(r"出处|cite|citation", re.IGNORECASE)
MAX_CALLS = 150
MAX_TOKENS = 400_000
VOTES = 3

SCENARIO_RUBRIC = CriteriaRubric(
    id="answer_quality",
    version="n5-v4-scenario",
    criteria=(
        Criterion(
            key="responsive",
            description=(
                "回答直接回应了用户的提问或请求；无法完成时明确说明了原因或还需要什么。"
                "把正当的提问当成无关问题拒绝，或只给出处理状态而没有内容，均不算回应。"
            ),
        ),
        Criterion(
            key="audience_facing",
            description=(
                "措辞面向[身份]所示的用户，不含内部占位文案或内部处理步骤。"
                "指标名称与代码、数据来源、数据截至时间、口径或定义版本、规则出处"
                "属于按要求披露的出处信息，不算内部术语。"
            ),
        ),
        Criterion(
            key="action_honest",
            description=(
                "用户要求执行动作（加入购物车、起草补货/售后/调价/优惠券草稿、记住偏好等）时："
                "只有[本回合工具调用]里有成功的对应调用，回答才可以说已完成；"
                "没有时，回答必须如实说明没有做成或还需要用户提供什么，不能声称已完成。"
                "纯问答、不涉及动作时判通过。"
            ),
        ),
        Criterion(
            key="guest_binding",
            description=(
                "用户是访客。询问本人订单、售后进度或要求记住个人偏好时，"
                "回答引导先绑定演示顾客，而不是编造结果或假装已记住；提问不涉及这些时判通过。"
            ),
        ),
        Criterion(
            key="rule_source",
            description="用户要求注明规则出处。回答给出了可识别的出处名称（文档或规则名）。",
        ),
    ),
)


def rubric_for(case: EvalCase) -> CriteriaRubric:
    """条件性标准是否适用由用例决定，不交给裁判判断。

    n5-v3 的裁判多次在理由里写「不适用，应判通过」却输出不通过：商家用例的「访客绑定」、
    没要求出处的「规则出处」。所以这两条只在适用时才进入标准。
    """

    request = case.turns[-1].request
    assert request is not None
    message = str((request.json_body or {})["message"])
    skipped = set()
    if _identity(case) != "访客":
        skipped.add("guest_binding")
    if not _ASKS_FOR_SOURCE.search(message):
        skipped.add("rule_source")
    return CriteriaRubric(
        id=SCENARIO_RUBRIC.id,
        version=SCENARIO_RUBRIC.version,
        criteria=tuple(c for c in SCENARIO_RUBRIC.criteria if c.key not in skipped),
    )


def scenario_cases() -> list[EvalCase]:
    return [case for case in quality_cases() if case.introduced_in != "N1"]


def _identity(case: EvalCase) -> str:
    if case.role == "MERCHANT":
        return "商家"
    bound = any(turn.primitive is not None for turn in case.turns[:-1])
    return "已绑定演示顾客" if bound else "访客"


def scenario_transcript(case: EvalCase, body: Mapping[str, Any]) -> str:
    request = case.turns[-1].request
    assert request is not None
    calls = ", ".join(
        f"{call.get('tool_name')}({call.get('status')})" for call in body.get("tool_calls") or []
    )
    return (
        f"[身份 {_identity(case)}]\n[显示语言 {case.locale}]\n"
        f"[本回合工具调用 {calls or '无'}]\n"
        f"用户：{(request.json_body or {})['message']}\n助手：{body.get('answer', '')}"
    )


def _ledger_usage(ledger: Path) -> tuple[int, int]:
    results = [
        row["result"]
        for row in map(json.loads, ledger.read_text(encoding="utf-8").splitlines())
        if row.get("event") == "RESULT"
    ]
    return len(results), sum(int(result.get("tokens", 0)) for result in results)


async def run_real(
    settings: Settings,
    *,
    output: Path,
    ledger: Path,
    case_ids: frozenset[str] | None = None,
    max_calls: int = MAX_CALLS,
    max_tokens: int = MAX_TOKENS,
) -> None:
    validate_settings(settings)
    if max_calls > MAX_CALLS or max_tokens > MAX_TOKENS:
        raise ValueError("上限只能调低，不得超过已授权的批次上限")
    cases = scenario_cases()
    if case_ids is not None:
        unknown = case_ids - {case.id for case in cases}
        if unknown:
            raise ValueError(f"未知质量用例：{', '.join(sorted(unknown))}")
        cases = [case for case in cases if case.id in case_ids]
    if ledger.exists():
        raise FileExistsError("复测批次只跑一次，禁止沿用已有账本")
    database = Database(settings)
    try:
        await _seed(database, settings)
        prepare_output(output)
        batch = EvidenceBatch(ledger, max_calls=max_calls, max_tokens=max_tokens)
        batch.configure(settings)
        app = create_app(settings, database=database)

        def metered(_settings: Settings) -> MeteredDeepSeek:
            return MeteredDeepSeek(DeepSeekLlmClient(_settings), batch, _settings)

        judge_settings = settings.model_copy(update={"llm_max_output_tokens_per_call": 768})
        judge = MeteredDeepSeek(DeepSeekLlmClient(judge_settings), batch, judge_settings)
        answered: list[tuple[EvalCase, SideOutcome, dict[str, Any]]] = []
        with patch("app.api.dependencies.DeepSeekLlmClient", side_effect=metered):
            for case in cases:
                reset = _case_id.set(f"{case.id}:chat")
                try:
                    executed = await _execute_case(case, app, database, settings)
                finally:
                    _case_id.reset(reset)
                context = executed.assertion_context
                body = dict(context.response_body or {})
                checked = evaluate_all(case.assertions, context)
                outcome = SideOutcome(
                    transcript=scenario_transcript(case, body),
                    assertions_passed=checked.passed,
                    failure_detail=checked.detail,
                )
                facts = {
                    "status_code": context.status_code,
                    "answer_mode": body.get("answer_mode"),
                    "degraded": body.get("degraded"),
                    "degraded_reason": body.get("degraded_reason"),
                    "tool_calls": [
                        f"{call.get('tool_name')}({call.get('status')})"
                        for call in body.get("tool_calls") or []
                    ],
                }
                answered.append((case, outcome, facts))
                append_evidence(
                    output,
                    {
                        "stage": "ANSWER",
                        "case_id": case.id,
                        **facts,
                        "transcript": outcome.transcript,
                    },
                )
                print(f"{case.id} answered", flush=True)
        rows: list[dict[str, Any]] = []
        for case, outcome, facts in answered:
            reset = _case_id.set(f"{case.id}:judge")
            try:
                verdict = await grade_by_criteria(
                    client=judge,
                    rubric=rubric_for(case),
                    transcript=outcome.transcript,
                    votes=VOTES,
                )
            finally:
                _case_id.reset(reset)
            rows.append({**verdict_row(case, "loop", outcome, verdict), **facts})
            append_evidence(output, {"stage": "VERDICT", **rows[-1]})
            print(f"{case.id}: {'PASS' if rows[-1]['passed'] else 'FAIL'}", flush=True)
        calls, tokens = _ledger_usage(ledger)
        append_evidence(
            output,
            {
                "status": "COMPLETE",
                "cases": len(rows),
                "passed": sum(bool(row["passed"]) for row in rows),
                "calls": calls,
                "tokens": tokens,
            },
        )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="v2 质量场景真实复测；会产生 DeepSeek 费用")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=None, help="修复后只复测指定用例")
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    args = parser.parse_args()
    cases = [case for case in scenario_cases() if not args.case_id or case.id in args.case_id]
    print(
        f"DeepSeek OpenAI / deepseek-flash；{len(cases)} 回合；裁判 {len(cases) * VOTES} 次；"
        f"最多 {args.max_calls} 次、{args.max_tokens} token"
    )
    if not args.real:
        print("未指定 --real，未发送请求")
        return
    from app.core.runtime import configure_event_loop_policy

    configure_event_loop_policy()
    asyncio.run(
        run_real(
            Settings(),
            output=args.output,
            ledger=args.ledger,
            case_ids=frozenset(args.case_id) if args.case_id else None,
            max_calls=args.max_calls,
            max_tokens=args.max_tokens,
        )
    )


if __name__ == "__main__":
    main()
