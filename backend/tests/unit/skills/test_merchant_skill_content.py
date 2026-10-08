"""N3 阶段 C Task 0：6 个商家经营 Skill 正文与用例集
（`plans/2026-09-21-n3-merchant-skills.md` Task 0）。

只测「这批 Skill 文件本身是否合格」，不测工具执行——工具由各自任务（Task 1、3、4、5、6）实现后
再补集成测试。本文件的断言对应计划 Task 0 明确列出的边界表与「复制后改」三件事。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.eval.skill_cases import load_skill_cases
from app.skills.loader import load_skills
from app.skills.spec import SkillLoadError
from app.tools.types import ToolRole

MERCHANT_ROOT = Path(__file__).resolve().parents[3] / "app" / "skills" / "merchant"

EXPECTED_NAMES = {
    "performance-insights",
    "inventory-operations",
    "catalog-listings",
    "pricing-promotions",
    "detail-export",
    "rules-metric-caliber",
    "customer-service-replies",
}


def test_merchant_skills_load_and_no_marketing_campaigns() -> None:
    specs = load_skills(MERCHANT_ROOT, roles=frozenset({ToolRole.MERCHANT}))
    names = {spec.name for spec in specs}
    assert names == EXPECTED_NAMES
    assert "marketing-campaigns" not in names


def test_copied_skills_declare_vendor_source_with_pinned_commit() -> None:
    copied = {
        "performance-insights",
        "inventory-operations",
        "catalog-listings",
        "pricing-promotions",
    }
    specs = {spec.name: spec for spec in load_skills(MERCHANT_ROOT)}
    for name in copied:
        assert "vendor/anthropic-commerce-agents@fd4d592" in specs[name].source


def test_borough_written_skills_declare_borough_source() -> None:
    specs = {spec.name: spec for spec in load_skills(MERCHANT_ROOT)}
    for name in ("detail-export", "rules-metric-caliber", "customer-service-replies"):
        assert specs[name].source == "borough"


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("inventory-operations", "只能起草"),
        ("catalog-listings", "只能起草"),
        ("pricing-promotions", "只能起草"),
    ],
)
def test_write_skills_state_draft_only_boundary(name: str, kind: str) -> None:
    del kind
    specs = {spec.name: spec for spec in load_skills(MERCHANT_ROOT)}
    body = specs[name].body
    assert "审批" in body
    assert "自批" in body or "自动应用" in body or "不能自批" in body


def test_performance_insights_forbids_causal_wording_without_evidence() -> None:
    specs = {spec.name: spec for spec in load_skills(MERCHANT_ROOT)}
    body = specs["performance-insights"].body
    assert "线索" in body
    assert "机制证据" in body


def test_detail_export_states_rows_never_enter_conversation() -> None:
    specs = {spec.name: spec for spec in load_skills(MERCHANT_ROOT)}
    body = specs["detail-export"].body
    assert "不进对话" in body or "不进入对话" in body


def test_rules_metric_caliber_forbids_inventing_formula() -> None:
    specs = {spec.name: spec for spec in load_skills(MERCHANT_ROOT)}
    body = specs["rules-metric-caliber"].body
    assert "不自拟公式" in body or "不得自拟公式" in body


def test_every_skill_has_cases_yaml_with_required_shapes() -> None:
    all_cases = load_skill_cases(MERCHANT_ROOT)
    assert set(all_cases) == EXPECTED_NAMES
    for name, cases in all_cases.items():
        assert len(cases) >= 4, f"{name} 用例数不足"
        # 每个 Skill 至少 2 条正确触发 + 1 条误触发 + 1 条边界反例；用 id 后缀区分。
        suffixes = {case.id.rsplit("-", 1)[-1] for case in cases}
        assert {"hit1", "hit2", "miss1", "boundary1"}.issubset(suffixes), (
            f"{name} 缺少必要的用例类别：{suffixes}"
        )


def test_marketing_campaigns_directory_does_not_exist() -> None:
    assert not (MERCHANT_ROOT / "marketing-campaigns").exists()


def test_malformed_skill_directory_still_rejected_by_loader(tmp_path: Path) -> None:
    """回归哨兵：确保新增 6 个真实 Skill 没有意外放宽加载器本身的校验。"""

    bad_root = tmp_path / "merchant"
    (bad_root / "bad-name!").mkdir(parents=True)
    with pytest.raises(SkillLoadError):
        load_skills(bad_root)
