"""Skill 单测的样例与目录构造辅助。"""

from __future__ import annotations

from pathlib import Path

from app.skills.registry import SkillRegistry
from app.tools.types import ToolRole

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def skill_md(
    name: str, *, description: str | None = None, version: object = 1, body: str = ""
) -> str:
    return (
        f"---\nname: {name}\ndescription: {description or f'{name} 的描述'}\n"
        f"version: {version}\nsource: borough\n---\n\n{body or f'{name} 的正文。'}\n"
    )


def write_skill(
    root: Path, name: str, *, description: str | None = None, version: object = 1, body: str = ""
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(
        skill_md(name, description=description, version=version, body=body), encoding="utf-8"
    )
    return path


def fixture_registry() -> SkillRegistry:
    return SkillRegistry.from_roots(
        {ToolRole.CUSTOMER: FIXTURES / "customer", ToolRole.MERCHANT: FIXTURES / "merchant"}
    )


def empty_registry() -> SkillRegistry:
    return SkillRegistry({})
