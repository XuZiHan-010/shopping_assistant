"""真实质量验收入口的免费演练，不代表模型质量通过。"""

import json

import pytest

from app.eval.n3_quality_acceptance import evaluate_skill_intents, evaluate_summaries, skill_cases
from app.llm.client import LlmToolCall, LlmTurn
from app.llm.fake import FakeLlmClient


@pytest.mark.asyncio
async def test_skill_intents_observe_model_calls_and_reject_wrong_choice() -> None:
    case = next(c for c in skill_cases() if c.id.endswith("hit1"))
    fake = FakeLlmClient(
        turns=[
            LlmTurn(
                text=None,
                tool_calls=[
                    LlmToolCall(
                        call_id="c1",
                        tool_name="load_skill",
                        arguments_json=json.dumps({"name": case.skill}),
                    )
                ],
                stop_reason="TOOL_USE",
                tokens=10,
            )
        ]
    )
    report, _ = await evaluate_skill_intents([case], llm_for=lambda _: fake)
    assert report["passed"] == report["calls"] == 1
    assert case.skill in fake.converse_calls[0].messages[0].content
    assert "<external-data" in fake.converse_calls[0].messages[1].content
    wrong = FakeLlmClient(
        turns=[
            LlmTurn(
                text="你好",
                tool_calls=[],
                stop_reason="END_TURN",
                tokens=10,
            )
        ]
    )
    report, _ = await evaluate_skill_intents([case], llm_for=lambda _: wrong)
    assert report["passed"] == 0
    assert report["failed_case_ids"] == [case.id]


@pytest.mark.asyncio
async def test_summary_evaluation_uses_real_redaction_and_counts_failures() -> None:
    fakes = []

    def factory(_):
        fake = FakeLlmClient(responses=["商品破损，顾客申请退货。13800138000"])
        fakes.append(fake)
        return fake

    report, rows = await evaluate_summaries(llm_for=factory)
    assert report["cases"] == report["calls"] == 8
    assert all("13800138000" not in str(f.calls) for f in fakes)
    assert all("13800138000" not in row["summary"] for row in rows)
    assert report["manual_review_required"] is True
