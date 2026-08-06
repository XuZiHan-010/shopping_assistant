"""机械拦截「指向当前阶段的前向引用」。

这是本轮两条缺陷共同的形状：`answer` 说「经营数据查询将在 B4 接入」、
`degraded_reason` 说「商家资料查询将在 B4 接入」，而 B4 就是正在合并的这个阶段——
它已经交付了。用户读到的是「功能还没上线」，实际是这次请求没查成。两处都躲过了
人工评审，因为它们分散在不同字段、不同分支，没有任何一条测试同时看得见它们。

拦截方式是**扫字符串**而不是断言某几句话：
1. `app/agent/` 下所有**非 docstring** 的字符串字面量——用户可见文案都在这里；
2. 已发布的 `docs/fixtures/chat/*.json` 里的所有字符串值——前端直接消费它们。

注释和 docstring 不在扫描范围：它们是写给开发者的，「B5 的 Reviewer 尚未接入」
这类说明必须留着。指向**后续**阶段的用户文案（「导出将在 B6 提供」）也是诚实的，
所以只禁当前阶段代号，不禁全部。
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest

#: 正在合并的阶段。**合并 B5 时把它改成 "B5"**——这条测试防的是「当前阶段把自己
#: 写成未来时态」，阶段推进后 B4 就变成合法的历史引用了。
CURRENT_STAGE = "B6"

#: `(?<![A-Za-z0-9])` 挡掉 `AB4`、`BR20260803`；`(?![0-9])` 挡掉 `B42`。
#: 只匹配大写 B：fixture 里的 UUID（`b24375c9-…`）是小写。
_STAGE_PATTERN = re.compile(rf"(?<![A-Za-z0-9]){CURRENT_STAGE}(?![0-9])")

_AGENT_DIR = Path(__file__).resolve().parents[3] / "app" / "agent"
_FIXTURES_DIR = Path(__file__).resolve().parents[4] / "docs" / "fixtures" / "chat"


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """收集所有 docstring 表达式的 id，扫描时跳过它们。

    docstring 是写给开发者的，允许提到阶段代号；用户可见文案不允许。
    """

    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _source_strings(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _docstring_nodes(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
    ]


def _agent_modules() -> list[Path]:
    modules = sorted(p for p in _AGENT_DIR.rglob("*.py") if "__pycache__" not in p.parts)
    assert modules, f"没有扫到任何模块，路径可能写错了：{_AGENT_DIR}"
    return modules


def _fixture_files() -> list[Path]:
    files = sorted(_FIXTURES_DIR.glob("*.json"))
    assert files, f"没有扫到任何 Fixture，路径可能写错了：{_FIXTURES_DIR}"
    return files


def _json_strings(value: Any, path: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        return [item for key, sub in value.items() for item in _json_strings(sub, f"{path}.{key}")]
    if isinstance(value, list):
        return [item for i, sub in enumerate(value) for item in _json_strings(sub, f"{path}[{i}]")]
    return []


@pytest.mark.parametrize("module", _agent_modules(), ids=lambda p: str(p.name))
def test_agent_source_strings_never_reference_the_current_stage(module: Path) -> None:
    offenders = [
        f"{module.name}:{lineno} {text!r}"
        for lineno, text in _source_strings(module)
        if _STAGE_PATTERN.search(text)
    ]

    assert not offenders, (
        f"用户可见文案不能提到正在合并的阶段 {CURRENT_STAGE}——它已经交付了，"
        f"说「将在 {CURRENT_STAGE} 接入」会让用户以为功能还没上线：\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("fixture", _fixture_files(), ids=lambda p: str(p.stem))
def test_shipped_fixtures_never_reference_the_current_stage(fixture: Path) -> None:
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    offenders = [
        f"{fixture.name} {where} {text!r}"
        for where, text in _json_strings(payload)
        if _STAGE_PATTERN.search(text)
    ]

    assert not offenders, (
        f"已发布的 Fixture 是前端直接消费的载荷，不能提到正在合并的阶段 {CURRENT_STAGE}：\n"
        + "\n".join(offenders)
    )


def test_the_detector_actually_flags_the_wording_it_is_meant_to_catch() -> None:
    """正控：确保上面两条不是「因为正则永远匹配不上」而绿的。

    列的三条都是本轮真实修掉的文案；后两条是常见的误报形状，必须**不**命中。
    """

    assert _STAGE_PATTERN.search("已识别指标和查询范围；经营数据查询将在 B6 接入。")
    assert _STAGE_PATTERN.search("商家资料查询将在 B6 接入")
    assert _STAGE_PATTERN.search("B6 接入受控查询后展示经营结果。")
    assert not _STAGE_PATTERN.search("BR20260803-0001")
    assert not _STAGE_PATTERN.search("b24375c9-1f09-5951-bbc4-09c4f4338ffc")


def test_docstrings_are_deliberately_out_of_scope() -> None:
    """docstring 里的阶段引用是写给开发者的，扫描必须放过它们。

    这条不是可有可无的说明：如果 `_docstring_nodes` 哪天失效，上面两条会开始因为
    模块 docstring 而失败，维护者的第一反应会是删掉 docstring 里的阶段说明——
    那正好把设计意图丢掉。
    """

    source = '"""模块说明提到 B4。"""\nx = "用户文案提到 B4"\n'
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    kept = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
    ]

    assert kept == ["用户文案提到 B4"]
