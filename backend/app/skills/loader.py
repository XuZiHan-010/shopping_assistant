"""Skill 文件解析与校验（N3 阶段 A Task 1）。

frontmatter 只接受四个键，且全部必填：`name`、`description`、`version`、`source`。
蓝图只要求前两个；缺 `version` 是违反 A4 的版本化要求，缺 `source` 是违反 R8 的来源说明要求。

YAML 一律 `yaml.safe_load`：Skill 虽是本系统资产，解析器也不该有执行任意对象构造的能力。
正文超长**拒绝加载，不截断**——Skill 的禁止项常写在末尾，截断会让它看起来加载成功、实际丢了约束。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import yaml

from app.skills.spec import SkillLoadError, SkillSpec
from app.tools.types import ToolRole

#: 单个 Skill 正文的默认字符上限；与 `Settings.skill_max_chars` 的默认值一致（有测试守着）。
SKILL_MAX_CHARS: Final = 8_000
#: 单回合 `load_skill` 次数的默认上限；与 `Settings.skill_max_per_turn` 的默认值一致。
SKILL_MAX_PER_TURN: Final = 3

#: 名字即目录名：小写字母开头，只含小写字母、数字与连字符，不可能携带路径分隔符。
NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_VERSION_PATTERN: Final = re.compile(r"^\d+(?:\.\d+)*$")
_REQUIRED_KEYS: Final = ("name", "description", "version", "source")
_DESCRIPTION_MAX_CHARS: Final = 600
_SOURCE_MAX_CHARS: Final = 200
_FENCE: Final = "---"
_FRONTMATTER_MAX_BYTES: Final = 4_096
SKILL_FILE: Final = "SKILL.md"


def parse_skill_md(
    text: str,
    *,
    roles: frozenset[ToolRole] = frozenset(),
    max_chars: int = SKILL_MAX_CHARS,
    origin: str = "SKILL.md",
) -> SkillSpec:
    """解析一份 `SKILL.md`；任何不合格都抛 `SkillLoadError`，不做修补。"""

    frontmatter, body = _split(text, origin)
    try:
        meta = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise SkillLoadError(f"{origin}：frontmatter 不是合法的安全 YAML") from exc
    if not isinstance(meta, dict):
        raise SkillLoadError(f"{origin}：frontmatter 必须是键值映射")
    unknown = sorted(str(key) for key in meta if key not in _REQUIRED_KEYS)
    if unknown:
        raise SkillLoadError(f"{origin}：frontmatter 含未约定的键 {', '.join(unknown)}")
    for key in _REQUIRED_KEYS:
        if meta.get(key) is None or (isinstance(meta[key], str) and not meta[key].strip()):
            raise SkillLoadError(f"{origin}：frontmatter 缺少必填键 {key}")

    name = meta["name"]
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise SkillLoadError(f"{origin}：name 须匹配 {NAME_PATTERN.pattern}")
    version = _version(meta["version"], origin)
    description = _text(meta["description"], "description", _DESCRIPTION_MAX_CHARS, origin)
    source = _text(meta["source"], "source", _SOURCE_MAX_CHARS, origin)

    body = body.strip()
    if not body:
        raise SkillLoadError(f"{origin}：正文为空")
    if len(body) > max_chars:
        raise SkillLoadError(
            f"{origin}：正文长度 {len(body)} 超过上限 {max_chars}，拒绝加载（不截断）"
        )
    return SkillSpec(
        name=name,
        version=version,
        roles=roles,
        body=body,
        max_chars=max_chars,
        description=description,
        source=source,
    )


def load_skills(
    root: Path,
    *,
    roles: frozenset[ToolRole] = frozenset(),
    max_chars: int = SKILL_MAX_CHARS,
) -> list[SkillSpec]:
    """扫描一个白名单根目录的**直接子目录**，按名字排序返回（Task 2，A4「不能访问任意路径」）。

    - 根目录必须是绝对路径、真实目录，其本身不能是符号链接 / junction。上级目录不逐级检查：
      生产根目录由 `Path(__file__).resolve()` 得出，上级链接在启动时已被解析掉，
      检查上级只会误伤合法的部署布局；
    - 每个子目录名须匹配 `NAME_PATTERN`，且与 frontmatter 的 `name` 一致；
    - 目录与 `SKILL.md` 都在 `resolve()` **之前**逐级检查链接（`resolve()` 会跟随链接），
      `resolve()` 之后再核一次仍在根目录之下；
    - 根目录里的普通文件与点开头的条目（`.gitkeep`）忽略；没有 `SKILL.md` 的子目录拒绝，
      不静默跳过——少加载一个 Skill 同样是「看起来成功、实际缺规则」。
    """

    if not root.is_absolute():
        raise SkillLoadError(f"Skill 根目录必须是绝对路径：{root}")
    reject_links(root, what="Skill 根目录")
    if not root.is_dir():
        raise SkillLoadError(f"Skill 根目录不存在：{root}")
    resolved_root = root.resolve(strict=True)

    specs: list[SkillSpec] = []
    for child in sorted(root.iterdir(), key=lambda entry: entry.name):
        if child.name.startswith("."):
            continue
        reject_links(child, what=f"Skill 目录 {child.name}")
        if not child.is_dir():
            continue
        if not NAME_PATTERN.fullmatch(child.name):
            raise SkillLoadError(f"Skill 目录名 {child.name!r} 不符合 {NAME_PATTERN.pattern}")
        skill_file = child / SKILL_FILE
        reject_links(skill_file, what=f"{child.name}/{SKILL_FILE}")
        if not skill_file.is_file():
            raise SkillLoadError(f"Skill 目录 {child.name} 缺少 {SKILL_FILE}")
        if not skill_file.resolve(strict=True).is_relative_to(resolved_root):
            raise SkillLoadError(f"{child.name}/{SKILL_FILE} 解析后不在 Skill 根目录之下")
        # 按字节预判：UTF-8 一个字符至多 4 字节，外加 frontmatter 余量；超过即拒绝，不读进内存。
        if skill_file.stat().st_size > max_chars * 4 + _FRONTMATTER_MAX_BYTES:
            raise SkillLoadError(f"{child.name}/{SKILL_FILE}：文件长度超过上限，拒绝加载")
        spec = parse_skill_md(
            skill_file.read_text(encoding="utf-8"),
            roles=roles,
            max_chars=max_chars,
            origin=f"{child.name}/{SKILL_FILE}",
        )
        if spec.name != child.name:
            raise SkillLoadError(
                f"Skill 目录名 {child.name!r} 与 frontmatter name {spec.name!r} 不一致"
            )
        specs.append(spec)
    return specs


def reject_links(path: Path, *, what: str) -> None:
    """符号链接与 Windows junction 一律拒绝：两者都能把白名单目录指到任意位置。"""

    if path.is_symlink() or path.is_junction():
        raise SkillLoadError(f"{what} 是符号链接或 junction，拒绝加载")


def _split(text: str, origin: str) -> tuple[str, str]:
    """按**整行** `---` 切分：只认第一行与其后第一个分隔行，正文里的分隔线原样保留。"""

    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise SkillLoadError(f"{origin}：缺少开头的 YAML frontmatter 分隔线")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FENCE:
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    raise SkillLoadError(f"{origin}：frontmatter 缺少结束分隔线")


def _version(value: object, origin: str) -> str:
    if isinstance(value, float):
        # YAML 把未加引号的 1.2 读成浮点数，1.10 还会变成 1.1：拒绝并说明怎么写。
        raise SkillLoadError(f'{origin}：带小数点的 version 须加引号，如 version: "1.2"')
    # bool 是 int 的子类：`version: true` 不是版本号。
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise SkillLoadError(f"{origin}：version 须为数字版本号")
    text = str(value).strip()
    if not _VERSION_PATTERN.fullmatch(text):
        raise SkillLoadError(f"{origin}：version 须为数字版本号（如 1 或 1.2）")
    return text


def _text(value: object, key: str, limit: int, origin: str) -> str:
    if not isinstance(value, str):
        raise SkillLoadError(f"{origin}：{key} 须为字符串")
    text = " ".join(value.split())
    if len(text) > limit:
        raise SkillLoadError(f"{origin}：{key} 超过 {limit} 字符")
    return text
