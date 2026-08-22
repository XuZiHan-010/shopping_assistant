from __future__ import annotations

from decimal import Decimal

import pytest

from app.llm.client import LlmBudget, LlmBudgetExceededError
from app.llm.fake import FakeLlmClient
from app.metrics.catalog import MetricPayload
from app.repositories.analytics import ResultColumn
from app.services.safe_query import QueryResult


def _facts():
    from app.services.answer_service import AnswerFacts

    return AnswerFacts(
        question="最近两天退货量趋势怎么样？",
        metric=MetricPayload(
            metric_code="return_count",
            display_name="退货量",
            unit="件",
            definition="退货商品件数",
            source="Borough 指标目录",
            owner="经营分析组",
            status="ACTIVE",
            generated=False,
            notice=None,
        ),
        query_result=QueryResult(
            columns=(
                ResultColumn("date", "日期", "DIMENSION"),
                ResultColumn("return_count", "退货量", "METRIC"),
            ),
            rows=[
                {"date": "2026-08-11", "return_count": Decimal("3")},
                {"date": "2026-08-17", "return_count": Decimal("15")},
            ],
            total_rows=2,
            truncated=False,
            source_tables=("returns",),
            plan_steps=("按日期汇总退货量",),
            export_spec=None,
            notes=(),
            non_additive=False,
        ),
    )


def _draft(answer: str = "8月11日退货量为 3 件，8月17日为 15 件。") -> str:
    return (
        '{"answer":' + repr(answer).replace("'", '"') + ',"recommendations":['
        '{"title":"关注趋势","evidence":"8月17日为 15 件。","action":"持续跟踪。"},'
        '{"title":"核对范围","evidence":"共 2 行数据。","action":"确认日期范围。"}]}'
    )


@pytest.mark.asyncio
async def test_unparsable_draft_is_retried_not_immediately_degraded() -> None:
    from app.schemas.chat import QualityStatus
    from app.services.quality_loop import QualityLoop

    llm = FakeLlmClient(responses=["这不是 JSON", _draft(), '{"passed":true,"issues":[]}'])

    outcome = await QualityLoop(max_attempts=3).run(
        _facts(), llm, llm, LlmBudget(max_calls=12, max_tokens=40_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert outcome.attempts == 2
    assert any("无法解析" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_missing_reviewer_is_visible_degradation_never_passed() -> None:
    from app.schemas.chat import QualityStatus
    from app.services.quality_loop import DegradeReason, QualityLoop

    outcome = await QualityLoop(max_attempts=3).run(
        _facts(),
        FakeLlmClient(responses=[_draft()]),
        None,
        LlmBudget(max_calls=12, max_tokens=40_000),
    )

    assert outcome.status is QualityStatus.DEGRADED
    assert outcome.reason is DegradeReason.UPSTREAM
    assert any("未执行独立复核" in note for note in outcome.notes)
    assert not any("通过" in note and "复核" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_validation_issues_are_fed_back_into_the_next_prompt() -> None:
    from app.schemas.chat import QualityStatus
    from app.services.quality_loop import QualityLoop

    llm = FakeLlmClient(
        responses=[_draft("退货量为 98765 件。"), _draft(), '{"passed":true,"issues":[]}']
    )

    outcome = await QualityLoop(max_attempts=3).run(
        _facts(), llm, llm, LlmBudget(max_calls=12, max_tokens=40_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert "98765" in llm.calls[1][1]


def test_reviewer_rejection_cannot_have_an_empty_issue_list() -> None:
    from pydantic import ValidationError

    from app.schemas.answer import ReviewVerdict

    with pytest.raises(ValidationError):
        ReviewVerdict.model_validate({"passed": False, "issues": []})


@pytest.mark.asyncio
async def test_per_request_budget_exhaustion_is_reported_as_budget_not_upstream() -> None:
    from app.services.quality_loop import DegradeReason, QualityLoop

    class RaisingLlmClient:
        def is_configured(self) -> bool:
            return True

        async def complete(self, **_: object) -> object:
            raise LlmBudgetExceededError("request cap")

    outcome = await QualityLoop(max_attempts=2).run(
        _facts(), RaisingLlmClient(), RaisingLlmClient(), LlmBudget(max_calls=1, max_tokens=100)
    )

    assert outcome.reason is DegradeReason.BUDGET


@pytest.mark.asyncio
async def test_invalid_reviewer_payload_is_fed_back_and_retried() -> None:
    """Reviewer 的非法 JSON 是一次不合格复核输出，不等同于 HTTP/网络不可用。"""

    from app.schemas.chat import QualityStatus
    from app.services.quality_loop import QualityLoop

    llm = FakeLlmClient(responses=[_draft(), "not-json", _draft(), '{"passed":true,"issues":[]}'])

    outcome = await QualityLoop(max_attempts=2).run(
        _facts(), llm, llm, LlmBudget(max_calls=8, max_tokens=25_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert outcome.attempts == 2
    assert any("Reviewer" in note and "无法解析" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_successful_http_with_empty_content_is_retried_as_invalid_output() -> None:
    """空正文是「模型输出不合格」，必须再给一轮，而不是当成上游宕机直接兜底。"""

    from app.schemas.chat import QualityStatus
    from app.services.quality_loop import QualityLoop

    llm = FakeLlmClient(responses=["", _draft(), '{"passed":true,"issues":[]}'])

    outcome = await QualityLoop(max_attempts=2).run(
        _facts(), llm, llm, LlmBudget(max_calls=8, max_tokens=25_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert outcome.attempts == 2
    assert any("空正文" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_advisory_notes_from_a_passing_reviewer_reach_quality_notes() -> None:
    """「通过，但建议补充同比」既不该触发重试，也不该被悄悄丢掉（R7 可见性）。"""

    from app.schemas.chat import QualityStatus
    from app.services.quality_loop import QualityLoop

    llm = FakeLlmClient(responses=[_draft(), '{"passed":true,"issues":["建议补充同比"]}'])

    outcome = await QualityLoop(max_attempts=2).run(
        _facts(), llm, llm, LlmBudget(max_calls=8, max_tokens=25_000)
    )

    assert outcome.status is QualityStatus.PASSED
    assert outcome.attempts == 1
    assert any("建议补充同比" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_daily_budget_exhaustion_says_so_instead_of_blaming_this_request() -> None:
    """日预算和单请求预算都归 BUDGET，但对用户是两件事：一个今天别再试，一个换个问题就行。"""

    from app.llm.client import LlmDailyBudgetExceededError
    from app.services.quality_loop import DegradeReason, QualityLoop

    class DailyCapClient:
        def is_configured(self) -> bool:
            return True

        async def complete(self, **_: object) -> object:
            raise LlmDailyBudgetExceededError

    outcome = await QualityLoop(max_attempts=2).run(
        _facts(), DailyCapClient(), DailyCapClient(), LlmBudget(max_calls=8, max_tokens=25_000)
    )

    assert outcome.reason is DegradeReason.BUDGET
    assert any("今日模型用量已达上限" in note for note in outcome.notes)
    assert not any("本次请求的模型预算" in note for note in outcome.notes)


@pytest.mark.asyncio
async def test_exhausted_attempts_return_the_deterministic_summary_as_validation_degrade() -> None:
    """轮次用尽必须落在 VALIDATION：说成「服务不可用」会把排查方向带到上游去。"""

    from app.schemas.chat import QualityStatus
    from app.services.quality_loop import DegradeReason, QualityLoop

    llm = FakeLlmClient(
        responses=[
            _draft("退货量为 98765 件。"),
            _draft("退货量为 98765 件。"),
        ]
    )

    outcome = await QualityLoop(max_attempts=2).run(
        _facts(), llm, llm, LlmBudget(max_calls=8, max_tokens=25_000)
    )

    assert outcome.status is QualityStatus.DEGRADED
    assert outcome.reason is DegradeReason.VALIDATION
    assert outcome.attempts == 2
    assert "合计 18" in outcome.draft.answer, "兜底必须是同一事实包的确定性摘要"
    assert "98765" not in outcome.draft.answer
