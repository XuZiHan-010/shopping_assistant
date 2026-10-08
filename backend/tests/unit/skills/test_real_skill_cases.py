"""11 份真实 Skill 的加载与冲突回归；脚本化模型只验证接线和权限。"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest

from app.eval.graders.assertions import AssertionContext, evaluate_all
from app.eval.skill_cases import load_skill_cases
from app.skills.registry import SkillRegistry
from app.tools.types import ToolRole
from tests.unit.agent.loop.loop_doubles import call, end_turn, tool_use_turn
from tests.unit.skills.skill_turns import run_turn_with_skills

SKILL_ROOT = Path(__file__).resolve().parents[3] / "app" / "skills"
CASES = [
    case
    for role in ("customer", "merchant")
    for batch in load_skill_cases(SKILL_ROOT / role).values()
    for case in batch
]


@pytest.fixture(scope="module")
def real_registry() -> SkillRegistry:
    return SkillRegistry.from_roots(
        {
            ToolRole.CUSTOMER: SKILL_ROOT / "customer",
            ToolRole.MERCHANT: SKILL_ROOT / "merchant",
        }
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
async def test_registered_case_runs_through_real_skill_loader(case, real_registry):  # type: ignore[no-untyped-def]
    """执行 YAML 期望的工具路径；意图选择质量仍需真实模型人工验收。"""

    assertions = [item for item in case.assertions if item.path is not None]
    load_names = [
        str(item.expected).removeprefix("load_skill:")
        for item in assertions
        if item.path == "tool_calls_include" and str(item.expected).startswith("load_skill:")
    ]
    scripted = (
        [tool_use_turn(*(call("load_skill", name=name) for name in load_names))]
        if load_names
        else []
    )
    scripted.append(end_turn("按店铺规则处理。"))
    request = case.turns[0].request
    assert request is not None and request.json_body is not None
    message = request.json_body["message"]
    outcome, messages = await run_turn_with_skills(
        real_registry, scripted, role=ToolRole(case.role), user_message=message
    )
    successful = tuple(f"load_skill:{name}" for name in outcome.loaded_skills) + tuple(
        result.display.tool_name
        for result in outcome.tool_results
        if result.ok and result.display.tool_name != "load_skill"
    )
    ctx = AssertionContext(
        status_code=200,
        code=None,
        audit_events=(),
        side_effects={},
        response_body={"answer": outcome.answer},
        skill_calls=successful,
    )
    assert evaluate_all(case.assertions, ctx).passed
    assert any(message in item.content for item in messages if item.role == "user")
    for name in outcome.loaded_skills:
        assert any(f'<skill name="{name}"' in msg.content for msg in messages if msg.role == "tool")


@pytest.mark.parametrize(
    ("role", "first", "second"),
    [
        (role, first, second)
        for role, names in (
            (ToolRole.CUSTOMER, sorted((SKILL_ROOT / "customer").glob("*/SKILL.md"))),
            (ToolRole.MERCHANT, sorted((SKILL_ROOT / "merchant").glob("*/SKILL.md"))),
        )
        for first, second in combinations((path.parent.name for path in names), 2)
    ],
)
async def test_real_skill_pairs_load_without_overwriting(
    role: ToolRole, first: str, second: str, real_registry: SkillRegistry
) -> None:
    outcome, messages = await run_turn_with_skills(
        real_registry,
        [
            tool_use_turn(call("load_skill", name=first), call("load_skill", name=second)),
            end_turn(),
        ],
        role=role,
    )
    assert outcome.loaded_skills == [first, second]
    assert "Borough 安全与业务规则 > 更具体的 Skill > 更一般的 Skill" in messages[0].content
    assert all(
        any(f'<skill name="{name}"' in msg.content for msg in messages) for name in (first, second)
    )
