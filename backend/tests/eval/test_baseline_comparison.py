"""N2 Task 5：新循环与冻结基线的结构对照可复现（§6.10 必测最后一条）。"""

from __future__ import annotations

from tests.eval.baseline_comparison import (
    DISCLAIMER,
    REPORT_PATH,
    SHARED_SKILLS,
    compare,
    render_report,
    shared_cases,
)


def test_comparison_uses_only_shared_legacy_capabilities() -> None:
    cases = shared_cases()
    assert cases, "质量集里没有双方共有能力的用例"
    assert {c.skill for c in cases} <= set(SHARED_SKILLS)


async def test_both_paths_complete_every_shared_case_without_degradation() -> None:
    for baseline, loop in await compare():
        assert baseline.completed and loop.completed, baseline.case_id
        assert not baseline.degraded and not loop.degraded, baseline.case_id
        assert baseline.assertions_passed == baseline.assertions_applicable > 0
        assert loop.assertions_passed == loop.assertions_applicable > 0
        # 同一个查询替身：两条路径取数次数一致，差异只在编排。
        assert baseline.query_calls == loop.query_calls


async def test_committed_report_is_reproducible() -> None:
    """报告落在 docs 里；改了任一路径却没重新生成，这里会失败。"""

    regenerated = render_report(await compare())
    assert REPORT_PATH.read_text(encoding="utf-8") == regenerated


def test_report_states_it_proves_structure_not_quality() -> None:
    """Fake LLM 对照不得被说成质量验证（计划 Task 5、路线图 §四第 7 条）。"""

    text = REPORT_PATH.read_text(encoding="utf-8")
    assert DISCLAIMER in text
    assert "只证明结构正确" in text
    assert "待人工验收" in text
