"""白名单目录与路径逃逸防护（PRD A4「加载器不能访问任意路径」，Astra N3-1 必审）。

两道防线：

1. 启动期扫描：只读白名单根目录的直接子目录，逐级拒绝符号链接 / junction，
   `resolve()` 后再核一次仍在根目录之下；
2. 运行期加载：只查启动时装进内存的字典，名字先过白名单格式——运行期**根本不碰文件系统**。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.skills.loader import load_skills
from app.skills.registry import SkillRegistry
from app.skills.spec import SkillLoadError
from app.tools.types import ToolRole
from tests.unit.skills.skill_doubles import write_skill


@pytest.mark.parametrize(
    "name",
    [
        "../merchant/pricing-promotions",  # 跨角色
        "../../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "search-discovery/../../x",
        "search-discovery\\..\\x",
        "search%2F..%2Fx",
        "Search-Discovery",  # 大写不在白名单格式内
        "search-discovery\x00",
        "search-discovery\n",
        "",
    ],
)
def test_path_escape_attempts_rejected(name: str, registry: SkillRegistry) -> None:
    with pytest.raises(SkillLoadError):
        registry.load(ToolRole.CUSTOMER, name)


def test_customer_cannot_load_merchant_skill(registry: SkillRegistry) -> None:
    with pytest.raises(SkillLoadError):
        registry.load(ToolRole.CUSTOMER, "pricing-promotions")


def test_merchant_cannot_load_customer_skill(registry: SkillRegistry) -> None:
    with pytest.raises(SkillLoadError):
        registry.load(ToolRole.MERCHANT, "search-discovery")


def test_mcp_role_has_no_skills(registry: SkillRegistry) -> None:
    with pytest.raises(SkillLoadError):
        registry.load(ToolRole.MCP_READONLY, "pricing-promotions")


def test_own_role_skill_loads(registry: SkillRegistry) -> None:
    spec = registry.load(ToolRole.CUSTOMER, "search-discovery")
    assert spec.name == "search-discovery"
    assert spec.roles == frozenset({ToolRole.CUSTOMER})


def test_runtime_load_does_not_touch_filesystem(tmp_skill_root: Path) -> None:
    """启动后删掉文件，加载照常：运行期只读内存，文件系统上的后续改动无从注入。"""
    path = write_skill(tmp_skill_root, "sample")
    registry = SkillRegistry.from_roots({ToolRole.CUSTOMER: tmp_skill_root})
    path.unlink()
    assert registry.load(ToolRole.CUSTOMER, "sample").name == "sample"


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:
        # Windows 无开发者模式时建不了符号链接；Linux CI 与 Railway 上该用例有效，不得删除。
        pytest.skip(f"本机无法创建符号链接：{exc}")


def test_symlink_inside_skill_root_is_rejected(tmp_skill_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    write_skill(outside, "evil")
    _symlink_or_skip(tmp_skill_root / "evil", outside / "evil")
    with pytest.raises(SkillLoadError, match="符号链接"):
        load_skills(tmp_skill_root)


def test_symlinked_skill_file_is_rejected(tmp_skill_root: Path, tmp_path: Path) -> None:
    outside = write_skill(tmp_path / "outside", "evil")
    (tmp_skill_root / "evil").mkdir()
    _symlink_or_skip(tmp_skill_root / "evil" / "SKILL.md", outside)
    with pytest.raises(SkillLoadError, match="符号链接"):
        load_skills(tmp_skill_root)


def test_symlinked_root_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    write_skill(real, "sample")
    _symlink_or_skip(tmp_path / "linked", real)
    with pytest.raises(SkillLoadError, match="符号链接"):
        load_skills(tmp_path / "linked")


@pytest.mark.skipif(os.name != "nt", reason="junction 只存在于 Windows")
def test_windows_junction_is_rejected(tmp_skill_root: Path, tmp_path: Path) -> None:
    """junction 不是符号链接（`is_symlink()` 为假），但同样会把目录指到根外。"""
    outside = tmp_path / "outside"
    write_skill(outside, "evil")
    link = tmp_skill_root / "evil"
    done = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside / "evil")],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        pytest.skip("本机无法创建 junction")
    with pytest.raises(SkillLoadError, match="符号链接"):
        load_skills(tmp_skill_root)


def test_relative_root_is_rejected() -> None:
    with pytest.raises(SkillLoadError, match="绝对路径"):
        load_skills(Path("relative/skills"))


def test_missing_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SkillLoadError, match="不存在"):
        load_skills(tmp_path / "nope")


def test_directory_name_must_match_frontmatter_name(tmp_skill_root: Path) -> None:
    path = write_skill(tmp_skill_root, "alpha")
    path.write_text(
        path.read_text(encoding="utf-8").replace("name: alpha", "name: beta"), encoding="utf-8"
    )
    with pytest.raises(SkillLoadError, match="目录名"):
        load_skills(tmp_skill_root)


def test_directory_name_outside_whitelist_is_rejected(tmp_skill_root: Path) -> None:
    (tmp_skill_root / "Bad_Name").mkdir()
    with pytest.raises(SkillLoadError, match="目录名"):
        load_skills(tmp_skill_root)


def test_directory_without_skill_md_is_rejected(tmp_skill_root: Path) -> None:
    """放错位置的目录不静默跳过：少加载一个 Skill 同样是看起来成功、实际缺规则。"""
    (tmp_skill_root / "orphan").mkdir()
    with pytest.raises(SkillLoadError, match=r"SKILL\.md"):
        load_skills(tmp_skill_root)


def test_plain_files_and_dot_entries_in_root_are_ignored(tmp_skill_root: Path) -> None:
    write_skill(tmp_skill_root, "sample")
    (tmp_skill_root / ".gitkeep").write_text("", encoding="utf-8")
    (tmp_skill_root / "README.md").write_text("说明", encoding="utf-8")
    assert [s.name for s in load_skills(tmp_skill_root)] == ["sample"]


def test_oversized_file_is_rejected(tmp_skill_root: Path) -> None:
    write_skill(tmp_skill_root, "sample", body="x" * 50)
    with pytest.raises(SkillLoadError, match="长度"):
        load_skills(tmp_skill_root, max_chars=10)


def test_loaded_skills_carry_given_roles(tmp_skill_root: Path) -> None:
    write_skill(tmp_skill_root, "sample")
    (spec,) = load_skills(tmp_skill_root, roles=frozenset({ToolRole.MERCHANT}))
    assert spec.roles == frozenset({ToolRole.MERCHANT})
