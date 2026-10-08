"""冻结基线与新工具循环在共有旧能力上的真实模型对照；只在已获 R3 授权后显式 ``--real`` 执行。

基线一侧不再重跑：直接复用 2026-10-06 冻结快照里的回答与代码断言结果（哈希校验）。
新循环一侧把同样 6 个问题发到 ``/api/v2/merchant/chat``，并套用基线用例原样的代码断言。
两侧回答都交给逐项判定裁判各判 3 票。70 次 / 15 万 token 是证据账本的硬上限。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.session import Database
from app.eval.acceptance_evidence import (
    EvidenceBatch,
    append_evidence,
    prepare_output,
    validate_settings,
)
from app.eval.cases import EvalCase, load_cases_from_directory
from app.eval.graders.assertions import AssertionContext, evaluate_all
from app.eval.graders.criteria_judge import (
    CriteriaJudgeResult,
    CriteriaRubric,
    Criterion,
    grade_by_criteria,
)
from app.eval.graders.language import narrative_matches_locale
from app.eval.n5_quality_real import DATASET, MeteredDeepSeek, _case_id, _seed
from app.llm.deepseek import DeepSeekLlmClient
from app.main import create_app
from app.services.seed_service import default_merchants

LOOP_PATH = "/api/v2/merchant/chat"
BASELINE_SNAPSHOT_SHA256 = "fa469702bcad6a38e3a71bfe5d98919d65f345ddf6f84d4d8cceec4293c37dbc"
MAX_CALLS = 70
MAX_TOKENS = 150_000
VOTES = 3
SIDES = ("baseline", "loop")

# 叙述语言是否与显示语言一致由 `narrative_matches_locale` 确定性判定，不在裁判标准里：
# n5-v2 的裁判曾三票一致把英文显示下的中文回答判成通过，又把英文回答判成中文。
RUBRICS: Mapping[str, CriteriaRubric] = {
    "answer_quality": CriteriaRubric(
        id="answer_quality",
        version="n5-v3",
        criteria=(
            Criterion(
                key="responsive",
                description=(
                    "回答直接给出了用户所问的信息；无法提供时明确说明了原因。"
                    "把经营相关的提问当成无关问题拒绝，或只给出处理状态而没有内容，均不算回应。"
                ),
            ),
            Criterion(
                key="merchant_facing",
                # 出处信息是产品要求披露的（PRD §12.3 #3、§12.5 #4），
                # n5-v2 的裁判曾把它当内部术语扣分。
                description=(
                    "措辞面向商家，不含内部占位文案或内部处理步骤。"
                    "指标名称与代码、数据来源、数据截至时间、口径或定义版本属于按要求披露的出处信息，"
                    "不算内部术语。"
                ),
            ),
        ),
    ),
    "greeting_quality": CriteriaRubric(
        id="greeting_quality",
        version="n5-v3",
        criteria=(
            Criterion(
                key="greeting",
                description=(
                    "回答是对问候的自然回应（问候、自我介绍或说明能帮什么），"
                    "不是无关内容或内部状态文案。"
                ),
            ),
            # 「简洁」在 n5-v2 里随票数摆动（同类问候 2:1 通过、2:1 不通过），不再作为判定依据。
            Criterion(
                key="polite",
                description="语气礼貌、切题；可以列出能提供的帮助，篇幅长短不作为判定依据。",
            ),
        ),
    ),
}


@dataclass(frozen=True)
class SideOutcome:
    transcript: str
    assertions_passed: bool
    failure_detail: str


def shared_cases() -> list[EvalCase]:
    """双方共有的旧能力（PRD A2）：质量集根目录里 N1 登记的基线用例。"""

    cases = [case for case in load_cases_from_directory(DATASET) if case.introduced_in == "N1"]
    if len(cases) != 6 or any(case.rubric_id not in RUBRICS for case in cases):
        raise ValueError("共有能力用例集发生变化，须重新核对费用授权")
    return cases


def _message(case: EvalCase) -> str:
    request = case.turns[-1].request
    assert request is not None
    return str((request.json_body or {})["message"])


def loop_request_body(case: EvalCase) -> dict[str, str]:
    return {"client_request_id": f"cmp-{case.id.lower()}", "message": _message(case)}


def _transcript(case: EvalCase, answer: object) -> str:
    return f"[显示语言 {case.locale}]\n用户：{_message(case)}\n助手：{answer}"


def loop_outcome(case: EvalCase, status_code: int, body: Mapping[str, Any]) -> SideOutcome:
    """新循环一侧沿用基线用例原样的代码断言，不另立口径。"""

    result = evaluate_all(
        case.assertions,
        AssertionContext(
            status_code=status_code,
            code=body.get("code"),
            audit_events=(),
            side_effects={},
            response_body=body,
        ),
    )
    return SideOutcome(
        transcript=_transcript(case, body.get("answer", "")),
        assertions_passed=result.passed,
        failure_detail=result.detail,
    )


async def execute_loop_side(
    case: EvalCase, client: AsyncClient, session_headers: Mapping[str, str]
) -> SideOutcome:
    response = await client.post(
        LOOP_PATH,
        json=loop_request_body(case),
        headers={
            **session_headers,
            "Accept": "application/json",
            "Accept-Language": case.locale,
            "X-Request-Id": f"baseline-comparison:{case.id}",
        },
    )
    body = response.json() if response.content else {}
    return loop_outcome(case, response.status_code, body if isinstance(body, dict) else {})


def load_baseline_side(
    path: Path, *, sha256: str, case_ids: Sequence[str]
) -> dict[str, SideOutcome]:
    """读取冻结快照；内容与登记哈希不一致或缺用例时拒绝，避免拿改过的基线做对照。"""

    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("基线冻结快照的哈希与登记值不一致")
    rows = {
        row["case_id"]: row
        for row in map(json.loads, raw.decode("utf-8").splitlines())
        if "case_id" in row
    }
    missing = [case_id for case_id in case_ids if case_id not in rows]
    if missing:
        raise ValueError(f"基线冻结快照缺少用例：{', '.join(missing)}")
    return {
        case_id: SideOutcome(
            transcript=rows[case_id]["transcript"],
            assertions_passed=not rows[case_id]["failure_detail"],
            failure_detail=rows[case_id]["failure_detail"],
        )
        for case_id in case_ids
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for side in SIDES:
        mine = [row for row in rows if row["side"] == side]
        summary[side] = {
            "total": len(mine),
            "passed": sum(bool(row["passed"]) for row in mine),
            "assertions_passed": sum(bool(row["assertions_passed"]) for row in mine),
            "language_ok": sum(bool(row["language_ok"]) for row in mine),
            "judge_passed": sum(bool(row["judge_passed"]) for row in mine),
            "split_votes": sum(not row["judge_unanimous"] for row in mine),
        }
    return summary


def verdict_row(
    case: EvalCase, side: str, outcome: SideOutcome, judge: CriteriaJudgeResult
) -> dict[str, Any]:
    """通过 = 代码断言、叙述语言（确定性）、裁判三层都通过。"""

    answer = outcome.transcript.split("助手：", 1)[-1]
    language_ok = narrative_matches_locale(answer, case.locale)
    return {
        "case_id": case.id,
        "side": side,
        "locale": case.locale,
        "skill": case.skill,
        "assertions_passed": outcome.assertions_passed,
        "failure_detail": outcome.failure_detail,
        "language_ok": language_ok,
        "rubric": f"{judge.rubric_id}@{judge.rubric_version}",
        "judge_score": judge.score,
        "judge_passed": judge.passed,
        "judge_unanimous": judge.unanimous,
        "votes": [
            {"score": vote.score, "verdicts": vote.verdicts, "reasons": vote.reasons}
            for vote in judge.votes
        ],
        "passed": outcome.assertions_passed and language_ok and judge.passed,
        "transcript": outcome.transcript,
    }


def render_report(
    rows: Sequence[Mapping[str, Any]], *, calls: int, tokens: int, max_calls: int, max_tokens: int
) -> str:
    names = {"baseline": "冻结基线（v1）", "loop": "新工具循环（v2）"}
    summary = summarize(rows)
    lines = [
        "| 路径 | 通过 | 代码断言通过 | 语言一致 | 裁判通过 | 三票不一致 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for side in SIDES:
        s = summary[side]
        if not s["total"]:
            continue
        lines.append(
            f"| {names[side]} | {s['passed']}/{s['total']} | {s['assertions_passed']}/{s['total']} "
            f"| {s['language_ok']}/{s['total']} | {s['judge_passed']}/{s['total']} "
            f"| {s['split_votes']} |"
        )
    lines += [
        "",
        f"真实调用合计 {calls} 次、{tokens} token（上限 {max_calls} 次 / {max_tokens} token）。",
        "",
        "| 用例 | 语言 | 路径 | 代码断言 | 语言一致 | 三票得分 | 结论 | 回答 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        answer = (
            str(row["transcript"]).split("助手：", 1)[-1].replace("\n", " ").replace("|", "\\|")
        )
        votes = " / ".join(
            "无效" if v["score"] is None else f"{v['score']:.2f}" for v in row["votes"]
        )
        lines.append(
            f"| {row['case_id']} | {row['locale']} | {names[row['side']]} "
            f"| {'通过' if row['assertions_passed'] else row['failure_detail']} "
            f"| {'是' if row['language_ok'] else '否'} | {votes} "
            f"| {'通过' if row['passed'] else '未通过'} | {answer} |"
        )
    return "\n".join(lines) + "\n"


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
    baseline: Path,
    output: Path,
    ledger: Path,
    report: Path,
    sides: Sequence[str] = SIDES,
    max_calls: int = MAX_CALLS,
    max_tokens: int = MAX_TOKENS,
) -> None:
    if max_calls > MAX_CALLS or max_tokens > MAX_TOKENS:
        raise ValueError("上限只能调低，不得超过已授权的批次上限")
    validate_settings(settings)
    cases = shared_cases()
    baseline_side = load_baseline_side(
        baseline, sha256=BASELINE_SNAPSHOT_SHA256, case_ids=[case.id for case in cases]
    )
    if ledger.exists() or report.exists():
        raise FileExistsError("对照批次只跑一次，禁止沿用或覆盖已有账本与报告")
    merchant = default_merchants()[0]
    bearer = next(
        token for token, owner in settings.demo_merchant_tokens.items() if owner == merchant.id
    )
    database = Database(settings)
    try:
        await _seed(database, settings)
        prepare_output(output)
        batch = EvidenceBatch(ledger, max_calls=max_calls, max_tokens=max_tokens)
        batch.configure(settings)
        app = create_app(settings, database=database)

        def metered(_settings: Settings) -> MeteredDeepSeek:
            return MeteredDeepSeek(DeepSeekLlmClient(_settings), batch, _settings)

        judge_settings = settings.model_copy(update={"llm_max_output_tokens_per_call": 512})
        judge = MeteredDeepSeek(DeepSeekLlmClient(judge_settings), batch, judge_settings)
        loop_side: dict[str, SideOutcome] = {}
        with patch("app.api.dependencies.DeepSeekLlmClient", side_effect=metered):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                for case in cases:
                    reset = _case_id.set(f"{case.id}:loop")
                    try:
                        # 每条用例各开一个会话：基线一侧也是逐条独立请求，且避开同会话限流。
                        opened = await client.post(
                            "/api/v2/merchant/sessions",
                            json={},
                            headers={"Authorization": f"Bearer {bearer}"},
                        )
                        opened.raise_for_status()
                        loop_side[case.id] = await execute_loop_side(
                            case, client, {"X-Session-Id": opened.json()["session_id"]}
                        )
                    finally:
                        _case_id.reset(reset)
                    append_evidence(
                        output,
                        {"stage": "LOOP_ANSWER", "case_id": case.id, **asdict(loop_side[case.id])},
                    )
                    print(f"{case.id} loop answered", flush=True)
        rows: list[dict[str, Any]] = []
        for case in cases:
            for side, outcome in (
                ("baseline", baseline_side[case.id]),
                ("loop", loop_side[case.id]),
            ):
                if side not in sides:
                    continue
                reset = _case_id.set(f"{case.id}:{side}:judge")
                try:
                    verdict = await grade_by_criteria(
                        client=judge,
                        rubric=RUBRICS[str(case.rubric_id)],
                        transcript=outcome.transcript,
                        votes=VOTES,
                    )
                finally:
                    _case_id.reset(reset)
                rows.append(verdict_row(case, side, outcome, verdict))
                append_evidence(output, {"stage": "VERDICT", **rows[-1]})
                print(f"{case.id} {side}: {'PASS' if rows[-1]['passed'] else 'FAIL'}", flush=True)
        calls, tokens = _ledger_usage(ledger)
        append_evidence(
            output,
            {"status": "COMPLETE", "summary": summarize(rows), "calls": calls, "tokens": tokens},
        )
        report.write_text(
            render_report(
                rows, calls=calls, tokens=tokens, max_calls=max_calls, max_tokens=max_tokens
            ),
            encoding="utf-8",
        )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="基线对照真实评测；会产生 DeepSeek 费用")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--loop-only", action="store_true", help="修复后复测：基线回答未变，只重判新循环一侧"
    )
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    args = parser.parse_args()
    cases = shared_cases()
    sides = ("loop",) if args.loop_only else SIDES
    print(
        f"DeepSeek OpenAI / deepseek-flash；新循环 {len(cases)} 回合；"
        f"裁判 {len(cases) * len(sides) * VOTES} 次；"
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
            baseline=args.baseline,
            output=args.output,
            ledger=args.ledger,
            report=args.report,
            sides=sides,
            max_calls=args.max_calls,
            max_tokens=args.max_tokens,
        )
    )


if __name__ == "__main__":
    main()
