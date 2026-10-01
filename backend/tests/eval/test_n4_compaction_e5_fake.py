"""E5 上下文压缩评测的 Fake LLM 结构校验（N4-A Task 5）。

只证明锚点与结构：两种策略在同一评测集上，身份、来源（含截至时间）、草稿版本、安全约束四项
保持率均为 100%。摘要策略用「什么都没保留」的 Fake 摘要跑——锚点必须靠回填保留，不靠摘要质量。
这不代表真实模型下的摘要质量；真实对比须按 R3 另行授权。
"""

from __future__ import annotations

import pytest

from app.agent.loop.compaction import CompactionStrategy, estimate_tokens, split_rounds
from app.eval.compaction_e5 import (
    DEFAULT_TRIGGER_TOKENS,
    KEEP_RECENT_ROUNDS,
    build_case,
    evaluate,
    load_cases,
)

RATES = ("identity_rate", "source_rate", "draft_version_rate", "safety_rate")


def test_dataset_has_enough_long_cases_that_cross_the_threshold() -> None:
    cases = load_cases()
    assert len(cases) >= 30
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["role"] for case in cases} == {"MERCHANT", "CUSTOMER"}
    for case in cases:
        built = build_case(case)
        assert estimate_tokens(built.messages) > DEFAULT_TRIGGER_TOKENS, case["id"]
        _prefix, rounds = split_rounds(built.messages)
        compacted = len(rounds) - KEEP_RECENT_ROUNDS
        assert case["depends_on"] and all(0 <= i < compacted for i in case["depends_on"]), case[
            "id"
        ]


def test_every_draft_and_metric_case_is_represented() -> None:
    cases = load_cases()
    tools = {r["tool"] for case in cases for i in case["depends_on"] for r in [case["rounds"][i]]}
    assert "query_metrics" in tools
    assert any(tool.startswith("draft_") for tool in tools)


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", list(CompactionStrategy))
async def test_both_strategies_keep_all_anchors_under_fake_llm(
    strategy: CompactionStrategy,
) -> None:
    report = await evaluate(load_cases(), strategy=strategy)

    assert report["cases"] >= 30
    assert report["compacted_cases"] == report["cases"]  # 每条都真的被压缩
    for rate in RATES:
        assert report[rate] == 1.0, (rate, report["failed_case_ids"])
    assert report["failed_case_ids"] == []
    assert 0 < report["mean_token_ratio"] < 1  # 压缩后确实变短
    assert report["llm_calls"] == (
        report["cases"] if strategy is CompactionStrategy.SUMMARIZATION else 0
    )


@pytest.mark.asyncio
async def test_drop_everything_summary_loses_early_user_statements() -> None:
    """诊断项：摘要吸收历史，Fake 摘要什么都不保留时，历史里顾客 / 商家的原话随之消失；
    清理只动工具结果，历史原话不受影响。这是选型依据之一，不是四项保持率。"""

    pruning = await evaluate(load_cases(), strategy=CompactionStrategy.TOOL_RESULT_PRUNING)
    summary = await evaluate(load_cases(), strategy=CompactionStrategy.SUMMARIZATION)

    assert pruning["history_user_rate"] == 1.0
    assert summary["history_user_rate"] == 0.0


def test_report_contains_no_conversation_text() -> None:
    """报告只含聚合数与用例 ID，不含对话原文（与 E5 记忆评测同一纪律）。"""

    import asyncio

    report = asyncio.run(evaluate(load_cases(), strategy=CompactionStrategy.SUMMARIZATION))
    text = repr(report)
    assert "别忘了" not in text and "忽略之前" not in text
