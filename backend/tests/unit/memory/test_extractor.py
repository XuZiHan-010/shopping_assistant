"""N4-B 事实抽取的发言者与来源边界。"""

import json

import pytest

from app.llm.client import LlmBudget, LlmMessage
from app.llm.fake import FakeLlmClient
from app.memory.extractor import MemoryExtractor


def _proposal(value: str, evidence: str, *, source_index: int = 0) -> str:
    return json.dumps(
        {
            "facts": [
                {
                    "category": "偏好",
                    "key": "颜色",
                    "value": value,
                    "source_index": source_index,
                    "evidence": evidence,
                }
            ]
        },
        ensure_ascii=False,
    )


def _budget() -> LlmBudget:
    return LlmBudget(max_calls=1, max_tokens=1000)


@pytest.mark.asyncio
async def test_explicit_user_fact_is_extracted_with_source() -> None:
    llm = FakeLlmClient(responses=[_proposal("喜欢素色", "我喜欢素色")])
    facts = await MemoryExtractor().extract(
        [LlmMessage("user", "我喜欢素色")], llm=llm, budget=_budget()
    )
    assert len(facts) == 1
    assert facts[0].value == "喜欢素色"
    assert facts[0].source_index == 0
    assert facts[0].evidence == "我喜欢素色"


@pytest.mark.asyncio
async def test_assistant_speculation_cannot_be_grounded_in_acknowledgement() -> None:
    llm = FakeLlmClient(responses=[_proposal("偏好素色", "嗯我看看", source_index=1)])
    facts = await MemoryExtractor().extract(
        [LlmMessage("assistant", "看起来你可能喜欢素色"), LlmMessage("user", "嗯我看看")],
        llm=llm,
        budget=_budget(),
    )
    assert facts == []


@pytest.mark.asyncio
async def test_assistant_source_index_is_rejected_even_with_matching_quote() -> None:
    llm = FakeLlmClient(responses=[_proposal("偏好素色", "你可能喜欢素色")])
    facts = await MemoryExtractor().extract(
        [LlmMessage("assistant", "你可能喜欢素色"), LlmMessage("user", "我再想想")],
        llm=llm,
        budget=_budget(),
    )
    assert facts == []


@pytest.mark.asyncio
async def test_tool_result_is_excluded_from_prompt_and_cannot_ground_fact() -> None:
    llm = FakeLlmClient(responses=[_proposal("喜欢素色", "喜欢素色")])
    facts = await MemoryExtractor().extract(
        [LlmMessage("tool", "顾客喜欢素色", tool_call_id="x"), LlmMessage("user", "你好")],
        llm=llm,
        budget=_budget(),
    )
    assert facts == []
    assert "顾客喜欢素色" not in llm.calls[0][1]


@pytest.mark.asyncio
async def test_empty_user_dialogue_skips_model() -> None:
    llm = FakeLlmClient(responses=[])
    assert (
        await MemoryExtractor().extract(
            [LlmMessage("assistant", "你好")], llm=llm, budget=_budget()
        )
        == []
    )
    assert llm.calls == []


@pytest.mark.asyncio
async def test_untrusted_model_fact_must_quote_selected_user_turn() -> None:
    llm = FakeLlmClient(responses=[_proposal("喜欢素色", "我喜欢素色", source_index=1)])
    facts = await MemoryExtractor().extract(
        [LlmMessage("user", "我喜欢素色"), LlmMessage("user", "我喜欢红色")],
        llm=llm,
        budget=_budget(),
    )
    assert facts == []


@pytest.mark.asyncio
async def test_overlong_fact_is_discarded() -> None:
    llm = FakeLlmClient(responses=[_proposal("长" * 501, "我喜欢素色")])
    assert (
        await MemoryExtractor().extract(
            [LlmMessage("user", "我喜欢素色")], llm=llm, budget=_budget()
        )
        == []
    )


@pytest.mark.asyncio
async def test_explicit_confirmation_of_assistant_question_is_grounded_in_user_reply() -> None:
    llm = FakeLlmClient(responses=[_proposal("喜欢素色", "是的", source_index=1)])
    facts = await MemoryExtractor().extract(
        [LlmMessage("assistant", "你喜欢素色吗？"), LlmMessage("user", "是的")],
        llm=llm,
        budget=_budget(),
    )
    assert [fact.value for fact in facts] == ["喜欢素色"]


@pytest.mark.asyncio
async def test_confirmation_without_specific_question_is_not_grounded() -> None:
    llm = FakeLlmClient(responses=[_proposal("喜欢素色", "是的", source_index=1)])
    facts = await MemoryExtractor().extract(
        [LlmMessage("assistant", "你有什么偏好？"), LlmMessage("user", "是的")],
        llm=llm,
        budget=_budget(),
    )
    assert facts == []


@pytest.mark.asyncio
async def test_model_cannot_drop_user_negation() -> None:
    llm = FakeLlmClient(responses=[_proposal("喜欢素色", "我不喜欢素色")])
    facts = await MemoryExtractor().extract(
        [LlmMessage("user", "我不喜欢素色")], llm=llm, budget=_budget()
    )
    assert facts == []
