"""Skill 回归用例框架（PRD A4「更新后回归」，N3 阶段 A Task 4，Astra N3-5 抽审）。

每个 Skill 目录可放 `cases.yaml`，格式复用 `app/eval/cases.py` 的 `EvalCase`；
`version` 变化时该 Skill 的用例必须全部重跑——`stale_skill_cases` 给出需要重跑的名单。
11 个业务 Skill 各自的用例在阶段 B、C 填。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.eval.skill_cases import load_skill_cases, stale_skill_cases
from app.skills.spec import SkillLoadError
from tests.unit.skills.skill_doubles import write_skill

RECORD = {"sample": "1", "other": "1"}


def _case(skill: str, case_id: str = "sample-001") -> str:
    return (
        f"- id: {case_id}\n"
        "  role: CUSTOMER\n"
        f"  skill: {skill}\n"
        "  risk: QUALITY\n"
        "  locale: zh-CN\n"
        "  introduced_in: N3\n"
        "  turns:\n"
        "    - actor: customer\n"
        "      request: {method: POST, path: /api/v2/shop/chat, json: {message: 找一双跑鞋}}\n"
        "  assertions:\n"
        "    - {type: http_status, expected: 200}\n"
    )


def bump_version(skill_dir: Path) -> None:
    path = skill_dir / "SKILL.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("version: 1", "version: 2"), encoding="utf-8"
    )


def test_skill_version_bump_requires_case_rerun(tmp_skill_root: Path) -> None:
    write_skill(tmp_skill_root, "sample")
    write_skill(tmp_skill_root, "other")
    assert stale_skill_cases(tmp_skill_root, last_run=RECORD) == set()
    bump_version(tmp_skill_root / "sample")
    assert stale_skill_cases(tmp_skill_root, last_run=RECORD) == {"sample"}


def test_never_run_skill_is_stale(tmp_skill_root: Path) -> None:
    write_skill(tmp_skill_root, "brand-new")
    assert stale_skill_cases(tmp_skill_root, last_run=RECORD) == {"brand-new"}


def test_cases_yaml_loads_as_eval_cases(tmp_skill_root: Path) -> None:
    write_skill(tmp_skill_root, "sample")
    (tmp_skill_root / "sample" / "cases.yaml").write_text(_case("sample"), encoding="utf-8")
    write_skill(tmp_skill_root, "other")  # 没有 cases.yaml 的 Skill 不出现在结果里
    cases = load_skill_cases(tmp_skill_root)
    assert list(cases) == ["sample"]
    assert [case.id for case in cases["sample"]] == ["sample-001"]


def test_case_must_belong_to_its_skill_directory(tmp_skill_root: Path) -> None:
    """用例的 `skill` 字段与所在目录不一致，版本变更时就会漏跑。"""
    write_skill(tmp_skill_root, "sample")
    (tmp_skill_root / "sample" / "cases.yaml").write_text(_case("other"), encoding="utf-8")
    with pytest.raises(SkillLoadError, match="other"):
        load_skill_cases(tmp_skill_root)


def test_invalid_case_file_is_rejected(tmp_skill_root: Path) -> None:
    write_skill(tmp_skill_root, "sample")
    (tmp_skill_root / "sample" / "cases.yaml").write_text("- id: x\n", encoding="utf-8")
    with pytest.raises(SkillLoadError, match=r"cases\.yaml"):
        load_skill_cases(tmp_skill_root)


def test_case_loading_honours_configured_skill_length(tmp_skill_root: Path) -> None:
    """评测侧与运行期用同一个长度上限；配置调大后，长 Skill 不能在评测侧被误拒。"""
    write_skill(tmp_skill_root, "long-skill", body="x" * 9_000)
    (tmp_skill_root / "long-skill" / "cases.yaml").write_text(_case("long-skill"), encoding="utf-8")
    assert list(load_skill_cases(tmp_skill_root, max_chars=10_000)) == ["long-skill"]
    assert stale_skill_cases(tmp_skill_root, last_run={}, max_chars=10_000) == {"long-skill"}
