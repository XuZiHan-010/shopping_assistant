from __future__ import annotations

from pathlib import Path

import pytest

from app.skills.registry import SkillRegistry
from tests.unit.skills.skill_doubles import fixture_registry


@pytest.fixture
def registry() -> SkillRegistry:
    return fixture_registry()


@pytest.fixture
def tmp_skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    return root
