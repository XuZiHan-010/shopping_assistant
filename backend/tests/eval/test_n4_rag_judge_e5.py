"""RAG 裁判评测的 Fake 演练（N4-C Task 7 步骤 3）：在花钱之前证明调用次数、引用解析与报告结构。"""

from __future__ import annotations

import json

import pytest

from app.eval.rag_e5 import load_rag_cases
from app.eval.rag_judge_e5 import (
    CALLS_PER_CASE,
    EXPECTED_CASES,
    _parse_verdict,
    judge_cases,
)
from app.llm.client import LlmTurn
from app.llm.fake import FakeLlmClient


def _turn(text: str) -> LlmTurn:
    return LlmTurn(text=text, tool_calls=[], stop_reason="END_TURN", tokens=10)


_GOOD = json.dumps(
    {
        "citations_supported": True,
        "faithful": True,
        "admits_not_covered": False,
        "unsupported_claims": 0,
    }
)
_REFUSE = json.dumps(
    {
        "citations_supported": False,
        "faithful": True,
        "admits_not_covered": True,
        "unsupported_claims": 0,
    }
)


@pytest.mark.asyncio
async def test_dry_run_makes_exactly_the_authorized_number_of_calls() -> None:
    cases = load_rag_cases()
    assert len(cases) == EXPECTED_CASES
    fakes: list[FakeLlmClient] = []

    def llm_for(request: str) -> FakeLlmClient:
        _case, kind = request.split(":")
        if kind == "answer":
            text = "依据 [业务/退货/业务流程/退货业务流程图.md]，买家发起退货申请。"
        else:
            text = _GOOD
        fake = FakeLlmClient(turns=[_turn(text)])
        fakes.append(fake)
        return fake

    report, rows = await judge_cases(cases, llm_for=llm_for)

    assert sum(len(f.converse_calls) for f in fakes) == report["llm_calls"]
    assert report["llm_calls"] == EXPECTED_CASES * CALLS_PER_CASE == 128
    assert report["judge_parse_failures"] == []
    judge_calls = [f.converse_calls[0] for f in fakes[1::2]]
    assert all(c.tools == [] for c in judge_calls)
    assert len(rows) == EXPECTED_CASES
    assert all(case["query"] not in repr(report) for case in cases)


@pytest.mark.asyncio
async def test_citation_outside_retrieved_documents_is_not_counted_correct() -> None:
    """模型引用了检索结果里没有的文档：即使裁判说支持，也不算引用正确（确定性兜底）。"""

    case = next(c for c in load_rag_cases() if c["id"] == "R-016")  # 退货流程，必有命中

    def llm_for(request: str) -> FakeLlmClient:
        text = "依据 [业务/不存在/文档.md]，可以退货。" if request.endswith("answer") else _GOOD
        return FakeLlmClient(turns=[_turn(text)])

    report, rows = await judge_cases([case], llm_for=llm_for)

    assert rows[0]["cited_exist"] is False
    assert report["citation_accuracy"] == 0.0
    assert report["failed_case_ids"] == ["R-016"]


@pytest.mark.asyncio
async def test_no_answer_case_scores_honest_refusal() -> None:
    case = next(c for c in load_rag_cases() if c["kind"] == "no_answer")

    def llm_for(request: str) -> FakeLlmClient:
        text = "知识库里没有覆盖这个问题。" if request.endswith("answer") else _REFUSE
        return FakeLlmClient(turns=[_turn(text)])

    report, _ = await judge_cases([case], llm_for=llm_for)

    assert report["refusal_cases"] == 1 and report["honest_refusal_rate"] == 1.0


def test_unparseable_judge_output_is_reported_not_guessed() -> None:
    assert _parse_verdict("不是 JSON") is None
    assert _parse_verdict(None) is None
    parsed = _parse_verdict(f"```json\n{_GOOD}\n```")
    assert parsed is not None and parsed.faithful is True


@pytest.mark.asyncio
async def test_hybrid_judge_uses_vector_retrieval() -> None:
    from app.knowledge.index_versions import IndexStatus, VectorSearchResult

    queries: list[str] = []

    class Vector:
        async def search(self, query: str) -> VectorSearchResult:
            queries.append(query)
            return VectorSearchResult(IndexStatus.FRESH, (), version_id=7)

    case = load_rag_cases()[0]
    report, _ = await judge_cases(
        [case],
        vector=Vector(),
        llm_for=lambda _: FakeLlmClient(turns=[_turn(_GOOD)]),
    )
    assert queries == [case["query"]]
    assert report["retrieval_mode"] == "HYBRID"


@pytest.mark.asyncio
async def test_failed_judge_stays_in_denominator() -> None:
    case = next(c for c in load_rag_cases() if c["id"] == "R-016")
    report, _ = await judge_cases(
        [case],
        llm_for=lambda _: FakeLlmClient(turns=[_turn("invalid")]),
    )
    assert report["answerable_with_hits"] == 1
    assert report["citation_accuracy"] == report["faithfulness"] == 0.0
    assert report["failed_case_ids"] == [case["id"]]
