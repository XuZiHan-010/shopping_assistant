"""冻结基线与新工具循环的真实模型对照入口：范围、冻结快照与汇总口径。

全部零费用：纯函数用例不碰模型，路由用例走脚本化 Fake LLM。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.eval.baseline_comparison_real import (
    SideOutcome,
    execute_loop_side,
    load_baseline_side,
    loop_outcome,
    loop_request_body,
    shared_cases,
    summarize,
    verdict_row,
)
from app.eval.graders.criteria_judge import CriteriaJudgeResult
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient
from tests.conftest import MERCHANT_ONE_AUTH
from tests.support.merchant_v2 import merchant_session_headers


def test_both_sides_are_asked_the_same_six_questions() -> None:
    cases = shared_cases()

    assert [case.id for case in cases] == [f"QLT-00{n}" for n in range(1, 7)]
    assert [loop_request_body(case)["message"] for case in cases] == [
        "今天销售额",
        "今天销售额",
        "最近7天退款金额",
        "昨天总 GMV 是多少？",
        "你好",
        "hi",
    ]
    assert [case.locale for case in cases] == [
        "zh-CN",
        "en-US",
        "zh-CN",
        "en-US",
        "zh-CN",
        "en-US",
    ]


def _snapshot(tmp_path: Path) -> tuple[Path, str]:
    rows = [
        {"status": "PREPARED", "complete": False},
        {
            "case_id": "QLT-001",
            "passed": False,
            "failure_detail": "[response_field] 路径 answer_mode 期望 'METRIC'，实得 'INVALID'",
            "judge_score": None,
            "transcript": "[显示语言 zh-CN]\n用户：今天销售额\n助手：只能回答经营相关的问题",
        },
        {
            "case_id": "QLT-003",
            "passed": False,
            "failure_detail": "",
            "judge_score": 0.4,
            "transcript": "[显示语言 zh-CN]\n用户：最近7天退款金额\n助手：4293.00 元",
        },
        {"case_id": "QLT-S5-001", "passed": True, "failure_detail": "", "transcript": "无关"},
        {"status": "COMPLETE", "cases": 3},
    ]
    path = tmp_path / "frozen.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), "utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_baseline_side_reuses_frozen_transcripts_and_code_assertion_outcomes(
    tmp_path: Path,
) -> None:
    path, digest = _snapshot(tmp_path)

    sides = load_baseline_side(path, sha256=digest, case_ids=("QLT-001", "QLT-003"))

    assert sides == {
        "QLT-001": SideOutcome(
            transcript="[显示语言 zh-CN]\n用户：今天销售额\n助手：只能回答经营相关的问题",
            assertions_passed=False,
            failure_detail="[response_field] 路径 answer_mode 期望 'METRIC'，实得 'INVALID'",
        ),
        "QLT-003": SideOutcome(
            transcript="[显示语言 zh-CN]\n用户：最近7天退款金额\n助手：4293.00 元",
            assertions_passed=True,
            failure_detail="",
        ),
    }


def test_baseline_snapshot_is_refused_when_it_differs_from_the_recorded_hash(
    tmp_path: Path,
) -> None:
    path, _ = _snapshot(tmp_path)

    with pytest.raises(ValueError, match="哈希"):
        load_baseline_side(path, sha256="0" * 64, case_ids=("QLT-001",))


def test_baseline_snapshot_missing_a_shared_case_is_refused(tmp_path: Path) -> None:
    path, digest = _snapshot(tmp_path)

    with pytest.raises(ValueError, match="QLT-002"):
        load_baseline_side(path, sha256=digest, case_ids=("QLT-001", "QLT-002"))


def test_loop_side_is_held_to_the_baseline_cases_own_code_assertions() -> None:
    case = shared_cases()[2]
    answer = "最近7天退款金额为 10 元。"

    ok = loop_outcome(case, 200, {"answer": answer, "answer_mode": "METRIC", "degraded": False})
    no_tool = loop_outcome(case, 200, {"answer": answer, "answer_mode": "CHAT", "degraded": False})
    degraded = loop_outcome(
        case, 200, {"answer": "部分", "answer_mode": "METRIC", "degraded": True}
    )
    unavailable = loop_outcome(case, 503, {"code": "LLM_UNAVAILABLE"})

    assert ok == SideOutcome(
        transcript="[显示语言 zh-CN]\n用户：最近7天退款金额\n助手：最近7天退款金额为 10 元。",
        assertions_passed=True,
        failure_detail="",
    )
    assert no_tool.assertions_passed is False
    assert "answer_mode" in no_tool.failure_detail
    assert degraded.assertions_passed is False
    assert "degraded" in degraded.failure_detail
    assert unavailable.assertions_passed is False
    assert unavailable.transcript.endswith("助手：")


def _judge(passed: bool) -> CriteriaJudgeResult:
    return CriteriaJudgeResult(
        rubric_id="answer_quality",
        rubric_version="n5-v3",
        score=1.0 if passed else 0.5,
        passed=passed,
        unanimous=True,
        votes=(),
    )


def test_wrong_narrative_language_fails_the_case_even_when_the_judge_passes_it() -> None:
    case = shared_cases()[3]  # QLT-004：英文显示、中文提问
    prefix = "[显示语言 en-US]\n用户：昨天总 GMV 是多少？\n助手："
    chinese = SideOutcome(prefix + "昨天的总 GMV 是 ¥10,607.00。", True, "")
    english = SideOutcome(prefix + "Yesterday's total GMV was 10,607.00.", True, "")

    wrong = verdict_row(case, "loop", chinese, _judge(True))
    right = verdict_row(case, "loop", english, _judge(True))

    assert (wrong["language_ok"], wrong["passed"]) == (False, False)
    assert (right["language_ok"], right["passed"]) == (True, True)


def test_language_is_no_longer_a_criterion_the_llm_judge_votes_on() -> None:
    from app.eval.baseline_comparison_real import RUBRICS

    for rubric in RUBRICS.values():
        assert "language" not in [criterion.key for criterion in rubric.criteria]


def _row(
    side: str, *, assertions: bool, judge: bool, unanimous: bool = True, language: bool = True
) -> dict[str, object]:
    return {
        "side": side,
        "assertions_passed": assertions,
        "language_ok": language,
        "judge_passed": judge,
        "judge_unanimous": unanimous,
        "passed": assertions and judge and language,
    }


def test_summary_counts_a_case_as_passed_only_when_every_layer_passes() -> None:
    rows = [
        _row("baseline", assertions=False, judge=False),
        _row("baseline", assertions=True, judge=False, unanimous=False),
        _row("baseline", assertions=True, judge=True),
        _row("loop", assertions=True, judge=True),
        _row("loop", assertions=False, judge=True),
        _row("loop", assertions=True, judge=True, language=False),
    ]

    summary = summarize(rows)

    assert summary["baseline"] == {
        "total": 3,
        "passed": 1,
        "assertions_passed": 2,
        "language_ok": 3,
        "judge_passed": 1,
        "split_votes": 1,
    }
    assert summary["loop"] == {
        "total": 3,
        "passed": 1,
        "assertions_passed": 2,
        "language_ok": 2,
        "judge_passed": 3,
        "split_votes": 0,
    }


@pytest.mark.integration
async def test_loop_side_puts_the_baseline_question_through_the_real_merchant_route(
    postgres_app: FastAPI, postgres_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeLlmClient(
        turns=[
            LlmTurn(
                text="你好，我可以帮你看经营数据。",
                tool_calls=[],
                stop_reason="END_TURN",
                tokens=10,
            )
        ]
    )
    monkeypatch.setattr(
        "app.api.routes.v2.merchant_chat.build_guarded_llm", lambda *args, **kwargs: fake
    )
    headers = await merchant_session_headers(postgres_client, MERCHANT_ONE_AUTH)
    case = shared_cases()[4]

    outcome = await execute_loop_side(case, postgres_client, headers)

    assert outcome == SideOutcome(
        transcript="[显示语言 zh-CN]\n用户：你好\n助手：你好，我可以帮你看经营数据。",
        assertions_passed=True,
        failure_detail="",
    )
    asked = [m.content for m in fake.converse_calls[0].messages if m.role == "user"]
    assert asked[-1].endswith("你好")
