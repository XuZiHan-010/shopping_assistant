"""Skill 回归用例框架（PRD A4「正确触发、误触发、多 Skill 冲突、更新后回归」，N3 阶段 A Task 4）。

- 每个 Skill 目录可放 `cases.yaml`，格式复用 `app.eval.cases.EvalCase`，用例的 `skill` 字段
  必须等于所在目录名——否则 `version` 变化时这条用例会被漏跑；
- 版本变更判定：`stale_skill_cases()` 对比上次运行记录的版本号，给出必须重跑的 Skill 名单；
  从未运行过的 Skill 同样算作需要运行。记录本身由评测流水线保存（N4/N5），这里只负责判定。

本模块属于评测（`app/eval/` 单向依赖：可以 import `app.skills`，生产代码不得 import 它），
运行期的工具循环不读 `cases.yaml`。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from app.eval.cases import EvalCase, load_cases_from_yaml
from app.skills.loader import SKILL_MAX_CHARS, load_skills, reject_links
from app.skills.spec import SkillLoadError

CASES_FILE: Final = "cases.yaml"


def load_skill_cases(root: Path, *, max_chars: int = SKILL_MAX_CHARS) -> dict[str, list[EvalCase]]:
    """按 Skill 名排序返回各自的用例；没有 `cases.yaml` 的 Skill 不出现在结果里。

    `max_chars` 须与运行期 `Settings.skill_max_chars` 一致，否则评测侧会误拒合法的长 Skill。
    """

    result: dict[str, list[EvalCase]] = {}
    for spec in load_skills(root, max_chars=max_chars):
        path = root / spec.name / CASES_FILE
        reject_links(path, what=f"{spec.name}/{CASES_FILE}")
        if not path.is_file():
            continue
        try:
            cases = load_cases_from_yaml(path)
        except (ValidationError, ValueError) as exc:
            raise SkillLoadError(f"{spec.name}/{CASES_FILE} 不是合法的用例列表：{exc}") from exc
        foreign = sorted({case.skill for case in cases if case.skill != spec.name})
        if foreign:
            raise SkillLoadError(
                f"{spec.name}/{CASES_FILE} 含属于其他 Skill 的用例：{', '.join(foreign)}"
            )
        result[spec.name] = cases
    return result


def stale_skill_cases(
    root: Path, *, last_run: Mapping[str, str], max_chars: int = SKILL_MAX_CHARS
) -> set[str]:
    """版本号与上次运行记录不一致（含从未运行）的 Skill：它们的用例必须全部重跑。"""

    return {
        spec.name
        for spec in load_skills(root, max_chars=max_chars)
        if last_run.get(spec.name) != spec.version
    }
