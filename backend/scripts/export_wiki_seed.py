"""从只读参考 Wiki 生成随镜像分发的确定性 JSON 知识种子。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.knowledge.wiki_import import parse_seed_wiki_tree

DEFAULT_WIKI_ROOT = (
    Path(__file__).resolve().parents[2]
    / "yshopping-merchant-ai 4"
    / "yshopping-merchant-ai"
    / "runtime"
    / "llm-wiki"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "app" / "knowledge" / "wiki_seed.json"
SEED_SOURCE = "Borough 团队维护（镜像知识种子）"


def render_wiki_seed(root: Path) -> bytes:
    """以稳定顺序和格式返回种子字节，供导出与漂移检查共用。"""

    payload = [
        {
            "source_path": entry.source_path,
            "category": entry.category,
            "title": entry.title,
            "content": entry.content,
            "is_complete": entry.is_complete,
            "source": SEED_SOURCE,
        }
        for entry in parse_seed_wiki_tree(root)
    ]
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def export_wiki_seed(root: Path, output: Path) -> None:
    output.write_bytes(render_wiki_seed(root))


def main() -> None:
    parser = argparse.ArgumentParser(description="生成镜像知识种子 JSON")
    parser.add_argument("--root", type=Path, default=DEFAULT_WIKI_ROOT, help="只读 llm-wiki 根目录")
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="wiki_seed.json 输出路径"
    )
    args = parser.parse_args()
    export_wiki_seed(args.root, args.output)
    print(f"知识种子已生成：{args.output}")


if __name__ == "__main__":
    main()
