"""评测骨架自测（N1-E Task 1）：分层校验、skip 三件套、通过率分母。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.eval.cases import (
    CaseResult,
    EvalCase,
    load_cases,
    summarize,
    validate_coverage,
)
from app.eval.graders.assertions import AssertionContext
from app.eval.graders.llm_judge import grade_with_rubric
from app.eval.runner import ExecutionOutcome, QualityRunner, RubricSpec
from app.llm.client import DEFAULT_LLM_CALL_OPTIONS, LlmBudget, LlmCallOptions, LlmResult

_FUTURE_DEADLINE = date.today() + timedelta(days=30)
_PAST_DEADLINE = date(2020, 1, 1)

BASE_CASE: dict[str, Any] = {
    "id": "EVAL-BASE-001",
    "role": "MERCHANT",
    "skill": "session",
    "risk": "SECURITY",
    "locale": "zh-CN",
    "turns": [
        {
            "actor": "merchant_a",
            "request": {"method": "GET", "path": "/api/v2/merchant/probe"},
        }
    ],
    "assertions": [{"type": "http_status", "expected": 200}],
}

SKIPPED_CASE: dict[str, Any] = {
    **BASE_CASE,
    "id": "EVAL-SKIP-001",
    "skip_reason": "被测对象尚未上线",
    "skip_owner": "sonnet",
    "skip_deadline": _FUTURE_DEADLINE.isoformat(),
}


def case(**overrides: Any) -> EvalCase:
    return EvalCase(**{**BASE_CASE, **overrides})


def passing() -> CaseResult:
    return CaseResult(case_id="pass-1", passed=True)


def failing() -> CaseResult:
    return CaseResult(case_id="fail-1", passed=False, failure_detail="示例失败")


def skipped() -> CaseResult:
    return CaseResult(case_id="skip-1", passed=False, skipped=True)


def test_skip_requires_reason_owner_and_deadline() -> None:
    for missing in ("skip_reason", "skip_owner", "skip_deadline"):
        data = {**SKIPPED_CASE}
        data.pop(missing)
        with pytest.raises(ValidationError):
            EvalCase(**data)


def test_skip_triple_together_is_valid() -> None:
    instance = EvalCase(**SKIPPED_CASE)
    assert instance.is_skipped is True


def test_case_must_have_at_least_one_code_assertion() -> None:
    with pytest.raises(ValidationError):
        EvalCase(**{**BASE_CASE, "assertions": []})


def test_skipped_cases_excluded_from_denominator() -> None:
    results = [passing(), failing(), skipped()]
    report = summarize(results)
    assert report.denominator == 2
    assert report.pass_rate == 0.5
    assert report.total == 3
    assert report.skipped == 1


def test_expired_skip_fails_loading() -> None:
    with pytest.raises(ValueError, match="skip 已过期"):
        load_cases([{**SKIPPED_CASE, "skip_deadline": _PAST_DEADLINE.isoformat()}])


def test_dataset_layer_coverage_is_enforced() -> None:
    with pytest.raises(ValueError, match="缺少分层"):
        validate_coverage([case(role="MERCHANT", locale="zh-CN")])


def test_dataset_layer_coverage_passes_with_full_matrix() -> None:
    cases = [
        case(id="EVAL-A", role="MERCHANT", locale="zh-CN"),
        case(id="EVAL-B", role="CUSTOMER", locale="zh-CN"),
        case(id="EVAL-C", role="MERCHANT", locale="en-US"),
        case(id="EVAL-D", role="CUSTOMER", locale="en-US"),
    ]
    validate_coverage(cases)


def test_case_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        EvalCase(**{**BASE_CASE, "unexpected_field": "x"})


def test_turn_rejects_both_request_and_primitive() -> None:
    with pytest.raises(ValidationError):
        EvalCase(
            **{
                **BASE_CASE,
                "turns": [
                    {
                        "actor": "merchant_a",
                        "request": {"method": "GET", "path": "/api/v2/merchant/probe"},
                        "primitive": {"name": "some.primitive"},
                    }
                ],
            }
        )


def test_loader_rejects_case_with_pii_like_string() -> None:
    tainted = {
        **BASE_CASE,
        "id": "EVAL-PII-001",
        "assertions": [{"type": "http_status", "expected": 200}],
        "turns": [
            {
                "actor": "merchant_a",
                "request": {
                    "method": "GET",
                    "path": "/api/v2/merchant/probe",
                    "query": {"phone": "13800001111"},
                },
            }
        ],
    }
    with pytest.raises(ValueError, match="真实个人信息"):
        load_cases([tainted])


# ---------------------------------------------------------------------------
# Task 3：执行器与三层评分。
# ---------------------------------------------------------------------------


class _FakeJudgeClient:
    """裁判层专用的最小 LLM 替身：记录收到的完整 payload 与调用次数。"""

    def __init__(self, *, text: str = "0.9") -> None:
        self._text = text
        self.call_count = 0
        self.last_payload = ""

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
        del fallback, options
        self.call_count += 1
        self.last_payload = f"{system}\n{user}"
        budget.charge_call()
        return LlmResult(text=self._text, tokens=10, degraded=False)


def _quality_case(**overrides: Any) -> EvalCase:
    return case(risk="QUALITY", **overrides)


def case_that_fails_assertion() -> EvalCase:
    return _quality_case(id="EVAL-QUALITY-FAIL")


def case_with_rubric() -> EvalCase:
    return _quality_case(id="EVAL-QUALITY-RUBRIC", rubric_id="answer_quality")


async def _mismatched_status_executor(_case: EvalCase) -> ExecutionOutcome:
    return ExecutionOutcome(
        assertion_context=AssertionContext(
            status_code=500, code=None, audit_events=(), side_effects={}
        ),
        transcript="不应该被读取——断言已经失败",
    )


async def _passing_executor(_case: EvalCase) -> ExecutionOutcome:
    return ExecutionOutcome(
        assertion_context=AssertionContext(
            status_code=200, code=None, audit_events=(), side_effects={}
        ),
        transcript="用户：帮我查一下昨天的 GMV\n助手：昨天 GMV 是 1200 元，数据来自订单表。",
    )


async def test_assertion_failure_short_circuits_judge() -> None:
    """代码断言失败时不得调用裁判。"""

    fake_judge = _FakeJudgeClient()
    runner = QualityRunner(
        executor=_mismatched_status_executor, judge_client=fake_judge, rubrics={}
    )

    result = await runner.run(case_that_fails_assertion())

    assert result.passed is False
    assert fake_judge.call_count == 0


async def test_judge_payload_hides_candidate_identity() -> None:
    fake_judge = _FakeJudgeClient()
    runner = QualityRunner(
        executor=_passing_executor,
        judge_client=fake_judge,
        rubrics={
            "answer_quality": RubricSpec(
                version="v1", prompt="评估回答是否准确、是否引用了数据来源。"
            )
        },
    )

    await runner.run(case_with_rubric(), candidate="new_loop")

    payload = fake_judge.last_payload
    for leak in ("new_loop", "baseline", "graph.py", "旧基线", "新循环"):
        assert leak not in payload


async def test_request_id_reaches_the_result_but_never_the_judge() -> None:
    """追踪 ID 随结果带出供报告回查（PRD §10.4），但不进入裁判载荷。"""

    async def traced_executor(case: EvalCase) -> ExecutionOutcome:
        outcome = await _passing_executor(case)
        return ExecutionOutcome(
            assertion_context=outcome.assertion_context,
            transcript=outcome.transcript,
            request_id="eval-trace-0001",
        )

    fake_judge = _FakeJudgeClient()
    runner = QualityRunner(
        executor=traced_executor,
        judge_client=fake_judge,
        rubrics={"answer_quality": RubricSpec(version="v1", prompt="评估回答是否准确。")},
    )

    judged = await runner.run(case_with_rubric())
    unjudged = await QualityRunner(
        executor=traced_executor, judge_client=fake_judge, rubrics={}
    ).run(_quality_case(id="EVAL-QUALITY-NO-RUBRIC"))

    assert judged.request_id == "eval-trace-0001"
    assert unjudged.request_id == "eval-trace-0001"
    assert "eval-trace-0001" not in fake_judge.last_payload


def test_response_field_assertion_requires_path_and_expected() -> None:
    from app.eval.cases import Assertion

    with pytest.raises(ValidationError):
        Assertion(type="response_field", expected="METRIC")
    with pytest.raises(ValidationError):
        Assertion(type="response_field", path="answer_mode")


def test_response_field_assertion_checks_nested_response_body() -> None:
    from app.eval.cases import Assertion
    from app.eval.graders.assertions import AssertionContext, evaluate_all

    ctx = AssertionContext(
        status_code=200,
        code=None,
        audit_events=(),
        side_effects={},
        response_body={"answer_mode": "METRIC", "degraded": False},
    )
    ok = evaluate_all(
        [Assertion(type="response_field", path="answer_mode", expected="METRIC")], ctx
    )
    assert ok.passed is True

    bad = evaluate_all([Assertion(type="response_field", path="degraded", expected=True)], ctx)
    assert bad.passed is False


def test_skill_assertions_read_evaluation_trace_not_public_response() -> None:
    from app.eval.cases import Assertion
    from app.eval.graders.assertions import AssertionContext, evaluate_all

    ctx = AssertionContext(
        status_code=200, code=None, audit_events=(), side_effects={},
        response_body={"answer": "已找到规则"},
        skill_calls=("load_skill:rules-metric-caliber",),
    )
    assert evaluate_all([
        Assertion(type="response_field", path="tool_calls_include",
                  expected="load_skill:rules-metric-caliber")
    ], ctx).passed
    assert not evaluate_all([
        Assertion(type="response_field", path="tool_calls_exclude",
                  expected="load_skill:rules-metric-caliber")
    ], ctx).passed
    assert evaluate_all([
        Assertion(type="response_field", path="tool_calls_exclude", expected="apply_draft")
    ], ctx).passed
    missing = AssertionContext(
        status_code=200, code=None, audit_events=(), side_effects={},
        response_body={"answer": "无证据"},
    )
    assert not evaluate_all([
        Assertion(type="response_field", path="tool_calls_exclude", expected="apply_draft")
    ], missing).passed


async def test_rubric_version_is_recorded_in_result() -> None:
    fake_judge = _FakeJudgeClient(text="0.8")

    result = await grade_with_rubric(
        client=fake_judge,
        rubric_id="answer_quality",
        version="v2",
        rubric_prompt="评估标准占位",
        transcript="占位对话",
    )

    assert result.rubric_version == "v2"
    assert result.score == 0.8
