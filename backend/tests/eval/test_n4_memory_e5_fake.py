"""E5 Fake LLM 结构校验：真实模型精度评估另需费用授权。"""

import json
from pathlib import Path

import pytest
import yaml

from app.eval.memory_e5 import evaluate
from app.llm.client import LlmBudget, LlmMessage
from app.llm.fake import FakeLlmClient
from app.memory.extractor import MemoryExtractor
from app.memory.filters import filter_candidate, filter_persisted

DATASET = (
    Path(__file__).resolve().parents[2]
    / "app/eval/datasets/memory/n4_e5_extraction.yaml"
)


@pytest.mark.asyncio
async def test_e5_fake_extraction_pipeline() -> None:
    cases = yaml.safe_load(DATASET.read_text(encoding="utf-8"))
    assert len(cases) >= 40
    assert len({case["id"] for case in cases}) == len(cases)
    passed = 0
    for case in cases:
        messages = []
        if "assistant" in case:
            messages.append(LlmMessage(role="assistant", content=case["assistant"]))
        messages.append(LlmMessage(role="user", content=case["user"]))
        index = len(messages) - 1
        proposal = {
            "category": "preference", "key": "style", "value": case["value"],
            "source_index": index, "evidence": case["user"],
        }
        fake = FakeLlmClient(responses=[json.dumps({"facts": [proposal]}, ensure_ascii=False)])
        candidates = await MemoryExtractor().extract(
            messages, llm=fake, budget=LlmBudget(max_calls=1, max_tokens=4000)
        )
        accepted = any(
            not filter_candidate(candidate).rejected
            and not filter_persisted(candidate).rejected
            for candidate in candidates
        )
        assert accepted is case["expected"], case["id"]
        assert len(fake.calls) == 1
        passed += 1
    assert passed == len(cases)


@pytest.mark.asyncio
async def test_e5_aggregate_report_uses_all_cases_without_real_calls() -> None:
    cases = yaml.safe_load(DATASET.read_text(encoding="utf-8"))
    responses = {}
    for case in cases:
        messages_count = 2 if "assistant" in case else 1
        proposal = {
            "category": "preference", "key": "style", "value": case["value"],
            "source_index": messages_count - 1, "evidence": case["user"],
        }
        responses[case["id"]] = FakeLlmClient(
            responses=[json.dumps({"facts": [proposal]}, ensure_ascii=False)]
        )
    evidence = []
    report = await evaluate(cases, llm_for_case=lambda case_id: responses[case_id],
                            on_case=evidence.append)
    assert report["cases"] == 40
    assert report["correct_writes"] == 20
    assert report["wrong_writes"] == 0
    assert report["missed"] == 0
    assert len(evidence) == 40
    assert sum(len(row["accepted"]) for row in evidence) == 20
    assert all("candidates" in row and "filters" in row for row in evidence)


@pytest.mark.asyncio
async def test_mem_016_real_model_candidates_no_longer_write_the_historical_value() -> None:
    """回放 2026-10-05 真实运行里模型对 MEM-016 的原始输出（错误写入 2/40 全部出自它）。

    模型把「这次我要彩色款」和「以前喜欢素色」各抽成一条同键候选，当时两条都被写入。
    之后加入的历史分句判定应只留下当前那一条；这里固定模型输出，不依赖模型是否再犯。
    """

    cases = yaml.safe_load(DATASET.read_text(encoding="utf-8"))
    case = next(item for item in cases if item["id"] == "MEM-016")
    recorded = {
        "facts": [
            {
                "category": "偏好", "key": "颜色偏好", "value": "彩色款",
                "source_index": 0, "evidence": "这次我要彩色款",
            },
            {
                "category": "偏好", "key": "颜色偏好", "value": "以前喜欢素色",
                "source_index": 0, "evidence": "以前喜欢素色",
            },
        ]
    }
    accepted: list[dict[str, object]] = []

    report = await evaluate(
        [case],
        llm_for_case=lambda _case_id: FakeLlmClient(
            responses=[json.dumps(recorded, ensure_ascii=False)]
        ),
        on_case=lambda row: accepted.extend(row["accepted"]),
    )

    assert report["wrong_writes"] == 0 and report["correct_writes"] == 1
    assert [item["value"] for item in accepted] == ["彩色款"]
