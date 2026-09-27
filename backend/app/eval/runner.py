"""Task 3：执行器与三层评分。

第一层代码断言永远先跑；断言失败直接判负，**不再调用 LLM 裁判**——不是为了
省钱，是为了不让「裁判打了高分所以放行」这条路径存在（E2）。第三层人工校准
只产出裁判与人工的一致性指标，不参与这里的自动判定，因此不在本模块内。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from app.eval.cases import EvalCase
from app.eval.graders.assertions import AssertionContext, evaluate_all
from app.eval.graders.llm_judge import JudgeResult, grade_with_rubric
from app.llm.client import LlmClient


@dataclass(frozen=True)
class ExecutionOutcome:
    """执行一条用例后，评分所需的全部证据。"""

    assertion_context: AssertionContext
    #: 已经脱去候选实现身份的纯对话文本，供裁判层使用；断言失败时不会被读取。
    transcript: str


@dataclass(frozen=True)
class RubricSpec:
    version: str
    prompt: str


@dataclass(frozen=True)
class CaseRunResult:
    case_id: str
    passed: bool
    failure_detail: str = ""
    judge: JudgeResult | None = None


Executor = Callable[[EvalCase], Awaitable[ExecutionOutcome]]


class QualityRunner:
    """代码断言 → （有 rubric 时）LLM 裁判，短路失败不调裁判。"""

    def __init__(
        self,
        *,
        executor: Executor,
        judge_client: LlmClient,
        rubrics: Mapping[str, RubricSpec],
    ) -> None:
        self._executor = executor
        self._judge_client = judge_client
        self._rubrics = rubrics

    async def run(self, case: EvalCase, *, candidate: str = "candidate") -> CaseRunResult:
        # `candidate` 只用于调用方标注结果归属（例如日志、报告分组），不会被
        # 传给 `_executor` 或 `grade_with_rubric`——裁判 payload 结构上看不到它。
        del candidate

        outcome = await self._executor(case)
        assertion_result = evaluate_all(case.assertions, outcome.assertion_context)
        if not assertion_result.passed:
            return CaseRunResult(case.id, passed=False, failure_detail=assertion_result.detail)

        if case.rubric_id is None:
            return CaseRunResult(case.id, passed=True)

        rubric = self._rubrics[case.rubric_id]
        judge = await grade_with_rubric(
            client=self._judge_client,
            rubric_id=case.rubric_id,
            version=rubric.version,
            rubric_prompt=rubric.prompt,
            transcript=outcome.transcript,
        )
        return CaseRunResult(case.id, passed=judge.passed, judge=judge)
