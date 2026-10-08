"""知识种子可独立于未入库的历史参考目录验证和再现。"""

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


def test_committed_wiki_seed_roundtrips_without_reference_checkout(tmp_path: Path) -> None:
    # CI 不包含 .gitignore 排除的只读参考目录。镜像种子本身就是随库资产，
    # 以它重建临时输入树，验证路径、类别、标题、完整性和导出格式可逐字再现。
    for entry in load_wiki_seed_entries():
        path = tmp_path / entry.source_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry.content, encoding="utf-8")
    assert _SEED_PATH.read_bytes() == _export_module.render_wiki_seed(tmp_path)

    # 本地保留参考快照时继续做原有差异检查；不把未入库目录变为 CI 前置。
    if _export_module.DEFAULT_WIKI_ROOT.is_dir():
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
