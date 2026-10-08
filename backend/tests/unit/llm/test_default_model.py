"""默认模型名迁移的哨兵：退役别名不得出现在任何**生效**配置里（AGENTS.md R3）。

只检查生效配置（默认值与赋值行），不检查叙述性文字：`.env.example`、`config.py` 里
「2026-08-17 用 deepseek-v4-flash 实测每个完整问题约 6000 token」这类注释记录的是当时
用哪个模型测出了什么，是历史事实，改掉反而是错的。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit.llm._transport import make_settings

_REPO_ROOT = Path(__file__).resolve().parents[4]
_RETIRED = ("deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner")
_CURRENT = "deepseek-flash"
_ASSIGNMENT = re.compile(r"^\s*LLM_MODEL\s*=\s*(?P<value>\S+)\s*$", re.MULTILINE)


def test_default_model_is_the_current_one() -> None:
    assert make_settings().llm_model == _CURRENT


def test_env_example_uses_the_current_model() -> None:
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert f"LLM_MODEL={_CURRENT}" in text


def test_env_example_has_no_retired_model_outside_comments() -> None:
    lines = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

    live = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    for retired in _RETIRED:
        assert not [line for line in live if retired in line], retired


@pytest.mark.parametrize("name", ["README.md", "README.en.md", "backend/README.md"])
def test_documented_llm_model_assignments_use_the_current_model(name: str) -> None:
    """文档里给人复制粘贴的 ``LLM_MODEL=`` 示例本身就是生效配置。"""

    text = (_REPO_ROOT / name).read_text(encoding="utf-8")

    values = [match["value"] for match in _ASSIGNMENT.finditer(text)]
    assert values, f"{name} 里没有找到 LLM_MODEL= 示例"
    assert set(values) == {_CURRENT}


@pytest.mark.parametrize("name", ["README.md", "README.en.md"])
def test_readme_does_not_advertise_a_retired_default(name: str) -> None:
    text = (_REPO_ROOT / name).read_text(encoding="utf-8")

    for retired in _RETIRED:
        assert f"default `{retired}`" not in text
        assert f"默认 `{retired}`" not in text
