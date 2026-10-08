"""`app/eval/` 单向依赖扫描（§5.6，E3「隔离」）。

`app/eval/` 可以 import 任何生产模块，但不得被任何生产模块 import。
本测试直接扫描源码，不依赖开发者记得手跑 `rg`。
"""

from __future__ import annotations

import re
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2] / "app"
_IMPORT_PATTERN = re.compile(r"^\s*(?:from|import)\s+app\.eval\b")


def test_app_eval_is_not_imported_by_production_code() -> None:
    offenders: list[str] = []
    for path in _APP_ROOT.rglob("*.py"):
        if "eval" in path.relative_to(_APP_ROOT).parts[:1]:
            continue  # app/eval/ 自身允许互相 import
        text = path.read_text(encoding="utf-8")
        if any(_IMPORT_PATTERN.match(line) for line in text.splitlines()):
            offenders.append(str(path.relative_to(_APP_ROOT)))
    assert not offenders, f"以下生产模块 import 了 app.eval：{offenders}"


def test_baseline_frozen_doc_exists() -> None:
    frozen_doc = _APP_ROOT / "eval" / "baseline" / "FROZEN.md"
    assert frozen_doc.is_file()
