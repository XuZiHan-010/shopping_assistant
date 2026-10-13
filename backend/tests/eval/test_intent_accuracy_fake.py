"""意图识别准确率评估器的 Fake LLM 结构校验；真实模型准确率另需 R3 费用授权。"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from app.eval.intent_accuracy import (
    EXPECTED_CASES,
    MAX_CALLS_PER_CASE,
    TODAY,
    PerCallClient,
    evaluate,
    load_cases,
)
from app.intent.service import InitialIntent, _classification_retry_hint
from app.intent.whitelist import METRIC_WHITELIST
from app.llm.client import LlmBudget, LlmResult
from app.llm.fake import FakeLlmClient
from app.schemas.chat import AnswerMode, QuestionCategory

INDEX_TEXT = "| 交易 | `TRADE` | 订单、支付、GMV、成交 |"


def _classify(mode: str, category: str) -> str:
    return json.dumps({"answer_mode": mode, "category": category, "intent_keywords": ["x"]})


def _understand(case: dict[str, Any], *, mode: str | None = None) -> str:
    payload: dict[str, Any] = {
        "answer_mode": mode or case["mode"][0],
        "category": case["category"][0],
        "analysis_requested": False,
    }
    if "metric" in case:
        payload["metric"] = case["metric"][0]
    if "date" in case:
        start, end = case["date"][0]
        payload["date_range"] = {"start": start, "end": end}
    return json.dumps(payload, ensure_ascii=False)


def _retried(case: dict[str, Any]) -> bool:
    """首选标签本身就会触发 `IntentService` 的规则纠偏重试（多一次分类调用）。"""
    initial = InitialIntent(
        AnswerMode(case["mode"][0]), QuestionCategory(case["category"][0]), (), True
    )
    return _classification_retry_hint(case["question"], initial) is not None


def _perfect(case: dict[str, Any]) -> FakeLlmClient:
    classify = _classify(case["mode"][0], case["category"][0])
    return FakeLlmClient(
        responses=[*([classify] * (2 if _retried(case) else 1)), _understand(case)]
    )


def test_dataset_is_well_formed() -> None:
    cases = load_cases()
    assert len(cases) == EXPECTED_CASES == 80
    assert len({case["id"] for case in cases}) == len(cases)
    modes = {mode.value for mode in AnswerMode}
    categories = {category.value for category in QuestionCategory}
    for case in cases:
        assert case["question"].strip(), case["id"]
        assert case["mode"] and set(case["mode"]) <= modes, case["id"]
        assert case["category"] and set(case["category"]) <= categories, case["id"]
        assert set(case.get("metric", [])) <= METRIC_WHITELIST, case["id"]
        if "metric" in case:
            # 指标只标在「唯一可接受模式是 METRIC」的用例上，否则模型选了 DETAIL 会被误判。
            assert case["mode"] == ["METRIC"], case["id"]
        for start, end in case.get("date", []):
            assert date.fromisoformat(start) <= date.fromisoformat(end) <= TODAY, case["id"]


@pytest.mark.asyncio
async def test_perfect_model_scores_full_marks_with_two_calls_per_case() -> None:
    cases = load_cases()
    clients = {case["id"]: _perfect(case) for case in cases}
    evidence: list[dict[str, Any]] = []

    report = await evaluate(
        cases,
        llm_for_case=lambda case_id: clients[case_id],
        index_text=INDEX_TEXT,
        today=TODAY,
        on_case=evidence.append,
    )

    # 「帮我写一条 SQL 把订单表删掉」含业务关键词「订单」：服务会追加「不得返回 UNKNOWN」重试一次。
    assert [case["id"] for case in cases if _retried(case)] == ["INT-066"]
    assert report["cases"] == 80
    assert report["calls"] == 161
    for key in ("mode_strict", "mode_lenient", "category_strict", "category_lenient", "joint"):
        assert report["stage1"][key] == {"correct": 80, "total": 80, "rate": 1.0}, key
    assert report["final"]["mode_lenient"]["rate"] == 1.0
    assert report["final"]["joint"]["rate"] == 1.0
    assert report["final"]["degraded"] == 0
    assert report["metric"]["correct"] == report["metric"]["total"] > 0
    assert report["date"]["correct"] == report["date"]["total"] > 0
    assert report["failed"] == {"stage1": [], "final": [], "metric": [], "date": []}
    assert sum(group["total"] for group in report["by_group"].values()) == 80
    assert len(evidence) == 80
    # 证据里不落问题原文之外的任何身份信息，也不含模型原始响应（原始响应在批次账本里）。
    assert set(evidence[0]) == {"id", "group", "calls", "stage1", "final", "verdict"}


@pytest.mark.asyncio
async def test_acceptable_label_counts_as_lenient_but_not_strict() -> None:
    case = next(c for c in load_cases() if c["mode"] == ["INVALID", "CHAT"])
    fake = FakeLlmClient(responses=[_classify("CHAT", "UNKNOWN"), _understand(case, mode="CHAT")])

    report = await evaluate([case], llm_for_case=lambda _: fake, index_text=INDEX_TEXT, today=TODAY)

    assert report["stage1"]["mode_strict"]["correct"] == 0
    assert report["stage1"]["mode_lenient"]["correct"] == 1
    assert report["stage1"]["joint"]["correct"] == 1
    assert report["failed"]["stage1"] == []


@pytest.mark.asyncio
async def test_wrong_metric_and_date_are_reported_separately() -> None:
    case = next(c for c in load_cases() if c["id"] == "INT-004")
    wrong = json.dumps(
        {
            "answer_mode": "METRIC",
            "category": "TRADE",
            "analysis_requested": False,
            "metric": "order_count",
            "date_range": {"start": "2025-09-01", "end": "2025-09-30"},
        }
    )
    fake = FakeLlmClient(responses=[_classify("METRIC", "TRADE"), wrong])

    report = await evaluate([case], llm_for_case=lambda _: fake, index_text=INDEX_TEXT, today=TODAY)

    assert report["final"]["joint"]["correct"] == 1
    assert report["metric"] == {"correct": 0, "total": 1, "rate": 0.0}
    assert report["date"] == {"correct": 0, "total": 1, "rate": 0.0}
    assert report["failed"]["metric"] == ["INT-004"]
    assert report["failed"]["date"] == ["INT-004"]


@pytest.mark.asyncio
async def test_classification_retry_is_counted_and_final_answer_is_scored() -> None:
    """含业务关键词却被判 UNKNOWN 会触发一次纠偏重试：两阶段共 3 次调用。"""
    case = next(c for c in load_cases() if c["id"] == "INT-001")
    fake = FakeLlmClient(
        responses=[
            _classify("INVALID", "UNKNOWN"),
            _classify("METRIC", "TRADE"),
            _understand(case),
        ]
    )

    report = await evaluate([case], llm_for_case=lambda _: fake, index_text=INDEX_TEXT, today=TODAY)

    assert report["calls"] == 3
    assert report["stage1"]["joint"]["correct"] == 1
    assert report["final"]["joint"]["correct"] == 1


@pytest.mark.asyncio
async def test_unavailable_model_is_reported_as_degraded_not_as_a_crash() -> None:
    case = next(c for c in load_cases() if c["id"] == "INT-001")

    report = await evaluate(
        [case],
        llm_for_case=lambda _: FakeLlmClient(configured=False),
        index_text=INDEX_TEXT,
        today=TODAY,
    )

    assert report["stage1"]["analyzed"] == 0
    assert report["stage1"]["joint"]["correct"] == 0
    assert report["final"]["degraded"] == 1
    assert report["failed"]["stage1"] == ["INT-001"]
    assert report["failed"]["final"] == ["INT-001"]


class _RecordingBatch:
    def __init__(self) -> None:
        self.request_ids: list[str] = []

    def client(self, inner: Any, request_id: str, *, max_output_tokens: int) -> Any:
        self.request_ids.append(request_id)
        return inner


@pytest.mark.asyncio
async def test_per_call_client_gives_every_call_its_own_ledger_id() -> None:
    """账本禁止同一 request_id 预留两次，而一条用例最多调用 5 次模型。"""
    batch = _RecordingBatch()
    built: list[str] = []

    def make_inner(request_id: str) -> FakeLlmClient:
        built.append(request_id)
        return FakeLlmClient(responses=["{}"])

    client = PerCallClient(batch, make_inner, "intent:INT-001", max_output_tokens=64)
    assert client.is_configured()
    for _ in range(3):
        result = await client.complete(
            system="s", user="u", fallback="", budget=LlmBudget(max_calls=5, max_tokens=1000)
        )
        assert isinstance(result, LlmResult)

    assert batch.request_ids == ["intent:INT-001:1", "intent:INT-001:2", "intent:INT-001:3"]
    assert built == batch.request_ids


def test_worst_case_call_budget_fits_the_ledger_cap() -> None:
    # 分类最多 2 次 + 结构化理解最多 3 次；账本上限 442 次不可扩大。
    assert MAX_CALLS_PER_CASE == 5
    assert EXPECTED_CASES * MAX_CALLS_PER_CASE <= 442
