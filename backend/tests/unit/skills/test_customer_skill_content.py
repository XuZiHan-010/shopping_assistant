"""N3 B 顾客 Skill 能被白名单加载，且不会引导模型使用越界能力。"""

from pathlib import Path

from app.eval.skill_cases import load_skill_cases
from app.services.v2.shop_chat import build_system_prompt
from app.skills.loader import load_skills
from app.tools.types import ToolRole

ROOT = Path(__file__).resolve().parents[3] / "app" / "skills" / "customer"
EXPECTED = {"search-discovery", "purchase-research", "planning-goals", "after-sales-service"}


def test_four_customer_skills_load_with_cases() -> None:
    specs = load_skills(ROOT, roles=frozenset({ToolRole.CUSTOMER}))
    assert {spec.name for spec in specs} == EXPECTED
    cases = load_skill_cases(ROOT)
    assert set(cases) == EXPECTED
    assert all(len(group) >= 4 for group in cases.values())


def test_skills_keep_borough_boundaries_and_sources() -> None:
    specs = {spec.name: spec for spec in load_skills(ROOT)}
    for name in ("search-discovery", "purchase-research", "planning-goals"):
        assert "vendor/anthropic-commerce-agents@fd4d592" in specs[name].source
    assert specs["after-sales-service"].source == "borough"
    for spec in specs.values():
        assert "不谈价" in spec.body
    for name in ("search-discovery", "purchase-research"):
        assert "本店" in specs[name].body and "不跨店" in specs[name].body
        assert "缺失" in specs[name].body
    assert "界面确认" in specs["after-sales-service"].body


def test_static_customer_prompt_keeps_boundaries_above_skills() -> None:
    prompt = build_system_prompt(None)
    for boundary in ("不谈价", "专业人士", "界面确认"):
        assert boundary in prompt
