"""检查提交的镜像知识种子是否与只读参考 Wiki 同步。"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.export_wiki_seed import DEFAULT_OUTPUT, DEFAULT_WIKI_ROOT, render_wiki_seed


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 wiki_seed.json 漂移")
    parser.add_argument("--root", type=Path, default=DEFAULT_WIKI_ROOT, help="只读 llm-wiki 根目录")
    parser.add_argument("--seed", type=Path, default=DEFAULT_OUTPUT, help="提交的 wiki_seed.json")
    args = parser.parse_args()
    expected = render_wiki_seed(args.root)
    actual = args.seed.read_bytes()
    if actual != expected:
        raise SystemExit(
            "wiki_seed.json 与参考 Wiki 不一致，请运行 python -m scripts.export_wiki_seed"
        )
    print("wiki_seed.json 漂移检查通过")


if __name__ == "__main__":
    main()
