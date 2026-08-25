"""随镜像分发的知识种子必须与只读参考 Wiki 保持同步。"""

from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path
from types import ModuleType

from app.knowledge.wiki_seed import load_wiki_seed_entries

_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_SEED_PATH = _BACKEND_ROOT / "app" / "knowledge" / "wiki_seed.json"


def _load_export_module() -> ModuleType:
    path = _BACKEND_ROOT / "scripts" / "export_wiki_seed.py"
    spec = importlib.util.spec_from_file_location("borough_export_wiki_seed", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_export_module = _load_export_module()


def test_committed_wiki_seed_matches_reference_wiki_byte_for_byte() -> None:
    assert _SEED_PATH.read_bytes() == _export_module.render_wiki_seed(
        _export_module.DEFAULT_WIKI_ROOT
    )


def test_wiki_seed_contains_only_the_expected_team_knowledge() -> None:
    entries = load_wiki_seed_entries()

    assert len(entries) == 21
    assert all(
        entry.source_path == "index/README.md" or entry.source_path.startswith("业务/")
        for entry in entries
    )
    assert Counter(entry.category for entry in entries) == {
        "UNKNOWN": 1,
        "TRADE": 2,
        "REFUND": 2,
        "CS_TICKET": 2,
        "COMPENSATION": 2,
        "COUPON": 2,
        "GOODS": 2,
        "MERCHANT_OTHER": 2,
        "IDENTITY": 2,
        "SCM": 2,
        "PLATFORM_RULE": 2,
    }
