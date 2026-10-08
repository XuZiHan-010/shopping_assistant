"""Skill 解析与校验（PRD A4，N3 阶段 A Task 1）。"""

from __future__ import annotations

import pytest

from app.skills.loader import SKILL_MAX_CHARS, SkillLoadError, parse_skill_md


def valid_frontmatter(name: str = "sample", version: object = 1) -> str:
    return (
        f"---\nname: {name}\ndescription: 样例 Skill 的一句话描述\n"
        f"version: {version}\nsource: borough\n---\n"
    )


def test_valid_skill_is_parsed() -> None:
    spec = parse_skill_md(valid_frontmatter() + "\n## 做法\n先查再答。\n")
    assert (spec.name, spec.description, spec.version, spec.source) == (
        "sample",
        "样例 Skill 的一句话描述",
        "1",
        "borough",
    )
    assert spec.body == "## 做法\n先查再答。"
    assert spec.max_chars == SKILL_MAX_CHARS


def test_missing_version_fails() -> None:
    with pytest.raises(SkillLoadError, match="version"):
        parse_skill_md("---\nname: a\ndescription: b\nsource: x\n---\nbody")


def test_missing_source_fails() -> None:
    """R8：复用蓝图须保留来源说明；Borough 新写的填 'borough'。"""
    with pytest.raises(SkillLoadError, match="source"):
        parse_skill_md("---\nname: a\ndescription: b\nversion: 1\n---\nbody")


def test_unsafe_yaml_is_rejected() -> None:
    """必须用 safe_load。"""
    evil = "---\nname: !!python/object/apply:os.system ['echo x']\n---\nbody"
    with pytest.raises(SkillLoadError):
        parse_skill_md(evil)


def test_body_over_limit_is_rejected_not_truncated() -> None:
    """A4：超限拒绝加载，不静默截断——截断会悄悄删掉后半段规则。"""
    with pytest.raises(SkillLoadError, match="长度"):
        parse_skill_md(valid_frontmatter() + "x" * (SKILL_MAX_CHARS + 1))


def test_body_at_limit_is_accepted() -> None:
    spec = parse_skill_md(valid_frontmatter() + "x" * SKILL_MAX_CHARS)
    assert len(spec.body) == SKILL_MAX_CHARS


def test_custom_limit_is_honoured() -> None:
    with pytest.raises(SkillLoadError, match="长度"):
        parse_skill_md(valid_frontmatter() + "x" * 11, max_chars=10)


@pytest.mark.parametrize(
    "text",
    [
        "name: a\n---\nbody",  # 没有开头分隔线
        "---\nname: a\ndescription: b\nversion: 1\nsource: x\nbody",  # 没有结束分隔线
        "---\n- a\n- b\n---\nbody",  # frontmatter 不是映射
        valid_frontmatter() + "   \n",  # 正文为空
    ],
)
def test_malformed_skill_is_rejected(text: str) -> None:
    with pytest.raises(SkillLoadError):
        parse_skill_md(text)


def test_unknown_frontmatter_key_is_rejected() -> None:
    """只接受约定的四个键：多出来的键说明格式漂移，不静默忽略。"""
    text = "---\nname: a\ndescription: b\nversion: 1\nsource: x\nallowed_tools: all\n---\nbody"
    with pytest.raises(SkillLoadError, match="allowed_tools"):
        parse_skill_md(text)


@pytest.mark.parametrize("name", ["Sample", "a", "has space", "under_score", "../x"])
def test_name_must_match_whitelist_pattern(name: str) -> None:
    with pytest.raises(SkillLoadError, match="name"):
        parse_skill_md(valid_frontmatter(name=f'"{name}"') + "body")


@pytest.mark.parametrize("version", ["''", "abc", "1.x", "-1", "true"])
def test_version_must_be_numeric(version: str) -> None:
    with pytest.raises(SkillLoadError, match="version"):
        parse_skill_md(valid_frontmatter(version=version) + "body")


def test_dotted_version_is_kept_as_string() -> None:
    assert parse_skill_md(valid_frontmatter(version='"1.2"') + "body").version == "1.2"


def test_frontmatter_separator_inside_body_is_kept() -> None:
    """正文里的 `---` 分隔线属于正文，不能被当成 frontmatter 的结束。"""
    spec = parse_skill_md(valid_frontmatter() + "第一段\n---\n第二段")
    assert spec.body == "第一段\n---\n第二段"


def test_unquoted_dotted_version_explains_quoting() -> None:
    """YAML 把未加引号的 1.2 读成浮点数（1.10 会变成 1.1），拒绝并提示加引号，而不是含糊报错。"""
    with pytest.raises(SkillLoadError, match="引号"):
        parse_skill_md(valid_frontmatter(version="1.2") + "body")
