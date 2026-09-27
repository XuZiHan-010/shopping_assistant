"""索引、按需加载与 `load_skill` 工具定义（PRD A4、A9，N3 阶段 A Task 3）。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.skills.loader import load_skills
from app.skills.registry import SkillRegistry, render_index
from app.skills.tool import LOAD_SKILL_TOOL, build_load_skill_tool
from app.tools.errors import GuardrailRejection
from app.tools.registry import ToolRegistry
from app.tools.types import ToolRole, WritePolicy
from tests.unit.skills.skill_doubles import empty_registry, write_skill
from tests.unit.tools.tool_doubles import ctx_for, customer_session, merchant_session


def make_skills(root: Path, *, order: list[str]) -> None:
    for name in order:
        write_skill(root, f"skill-{name}", description=f"{name} 的描述")


def shuffle_mtime(root: Path) -> None:
    """把目录的修改时间倒过来排：发现顺序若依赖 mtime，索引就会变。"""
    now = time.time()
    for offset, child in enumerate(sorted(root.iterdir(), reverse=True)):
        os.utime(child, (now + offset * 10, now + offset * 10))


def test_index_bytes_are_stable_regardless_of_discovery_order(tmp_skill_root: Path) -> None:
    make_skills(tmp_skill_root, order=["b", "a", "c"])
    first = render_index(load_skills(tmp_skill_root))
    shuffle_mtime(tmp_skill_root)
    second = render_index(load_skills(tmp_skill_root))
    assert first == second
    assert first.index("skill-a") < first.index("skill-b") < first.index("skill-c")


def test_index_order_does_not_depend_on_input_order(tmp_skill_root: Path) -> None:
    make_skills(tmp_skill_root, order=["b", "a", "c"])
    specs = load_skills(tmp_skill_root)
    assert render_index(specs) == render_index(list(reversed(specs)))


def test_index_contains_description_but_not_body(registry: SkillRegistry) -> None:
    sample = registry.load(ToolRole.CUSTOMER, "search-discovery")
    idx = registry.render_index(ToolRole.CUSTOMER)
    assert sample.description in idx
    assert sample.body not in idx
    assert "search_products" not in idx  # 正文里的做法不进索引


def test_index_names_version_and_load_tool(registry: SkillRegistry) -> None:
    idx = registry.render_index(ToolRole.CUSTOMER)
    assert "`search-discovery`" in idx and "v1" in idx
    assert LOAD_SKILL_TOOL in idx


def test_index_states_fixed_conflict_precedence(registry: SkillRegistry) -> None:
    """冲突裁决规则写在静态提示里，不依赖任何 Skill 正文（Task 4）。"""
    idx = registry.render_index(ToolRole.MERCHANT)
    assert "Borough 安全与业务规则 > 更具体的 Skill > 更一般的 Skill" in idx


def test_index_is_per_role(registry: SkillRegistry) -> None:
    assert "pricing-promotions" not in registry.render_index(ToolRole.CUSTOMER)
    assert "search-discovery" not in registry.render_index(ToolRole.MERCHANT)


def test_empty_index_renders_nothing() -> None:
    assert render_index([]) == ""
    assert empty_registry().render_index(ToolRole.CUSTOMER) == ""


def test_names_are_sorted(tmp_skill_root: Path) -> None:
    make_skills(tmp_skill_root, order=["c", "a", "b"])
    registry = SkillRegistry.from_roots({ToolRole.CUSTOMER: tmp_skill_root})
    assert registry.names(ToolRole.CUSTOMER) == ["skill-a", "skill-b", "skill-c"]
    assert registry.names(ToolRole.MERCHANT) == []


async def test_load_skill_guardrail_accepts_only_the_role_index(registry: SkillRegistry) -> None:
    """合法取值只来自当前角色的索引；不在索引里的名字由护栏交还模型，而不是致命错误。"""
    spec = build_load_skill_tool(registry)
    assert spec is not None and spec.guardrail is not None and spec.option_source is None
    customer, merchant = ctx_for(customer_session()), ctx_for(merchant_session())
    await spec.guardrail(customer, spec.args_model(name="search-discovery"))
    await spec.guardrail(merchant, spec.args_model(name="pricing-promotions"))
    for ctx, name in ((customer, "pricing-promotions"), (merchant, "search-discovery")):
        with pytest.raises(GuardrailRejection) as exc:
            await spec.guardrail(ctx, spec.args_model(name=name))
        assert exc.value.check.code == "SKILL_NOT_IN_INDEX"


def test_load_skill_tool_is_read_only_and_passes_registry_self_check(
    registry: SkillRegistry,
) -> None:
    spec = build_load_skill_tool(registry)
    assert spec is not None
    assert spec.name == LOAD_SKILL_TOOL
    assert spec.write_policy is WritePolicy.READ_ONLY
    assert set(spec.args_model.model_fields) == {"name"}
    ToolRegistry().register(spec)  # 走 §6.9 注册自检


def test_load_skill_tool_only_on_roles_with_skills(tmp_skill_root: Path) -> None:
    write_skill(tmp_skill_root, "only-merchant")
    registry = SkillRegistry.from_roots({ToolRole.MERCHANT: tmp_skill_root})
    spec = build_load_skill_tool(registry)
    assert spec is not None and spec.roles == frozenset({ToolRole.MERCHANT})


def test_no_load_skill_tool_when_every_index_is_empty() -> None:
    assert build_load_skill_tool(empty_registry()) is None


async def test_load_skill_executor_returns_spec_payload(registry: SkillRegistry) -> None:
    spec = build_load_skill_tool(registry)
    assert spec is not None
    output = await spec.executor(
        ctx_for(customer_session()), spec.args_model(name="search-discovery")
    )
    assert output.payload is registry.load(ToolRole.CUSTOMER, "search-discovery")


@pytest.mark.parametrize("name", ["x" * 65, ""])
def test_load_skill_args_reject_out_of_range_names(registry: SkillRegistry, name: str) -> None:
    spec = build_load_skill_tool(registry)
    assert spec is not None
    with pytest.raises(ValueError):
        spec.args_model(name=name)
