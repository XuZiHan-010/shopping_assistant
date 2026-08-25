"""把参考项目旧 Wiki 导入 ``knowledge_documents``。

参考目录是只读输入：本脚本仅读取 Markdown，绝不改写、重命名或格式化其中任何
文件。旧 DDL 与指标调用说明会描述并不存在于 Borough 的表结构，故明确排除。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.config import Settings
from app.core.runtime import configure_event_loop_policy
from app.db.session import Database
from app.knowledge.wiki_import import parse_seed_wiki_tree
from app.repositories.knowledge import KnowledgeRepository


async def _import(root: Path, *, overwrite: bool) -> tuple[int, int]:
    settings = Settings()
    database = Database(settings)
    entries = parse_seed_wiki_tree(root)
    created = 0
    async with database.session() as session:
        repository = KnowledgeRepository(session)
        for entry in entries:
            if overwrite:
                await repository.upsert_by_source_path(
                    source_path=entry.source_path,
                    category=entry.category,
                    title=entry.title,
                    content=entry.content,
                    source="Borough 团队维护（自旧 Wiki 导入）",
                    is_complete=entry.is_complete,
                )
                created += 1
            elif await repository.insert_if_absent_by_source_path(
                source_path=entry.source_path,
                category=entry.category,
                title=entry.title,
                content=entry.content,
                source="Borough 团队维护（自旧 Wiki 导入）",
                is_complete=entry.is_complete,
            ):
                created += 1
        await session.commit()
    await database.dispose()
    return created, len(entries) - created


def main() -> None:
    parser = argparse.ArgumentParser(description="导入旧 Wiki 到 knowledge_documents")
    parser.add_argument("--root", required=True, type=Path, help="llm-wiki 目录")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="强制覆盖同路径的后台维护内容；默认仅补充缺失文档",
    )
    args = parser.parse_args()
    # Windows 的 ProactorEventLoop 不能驱动 psycopg async；Web 入口已在运行时
    # 配置，独立维护脚本也必须在 asyncio.run 前配置同一策略。
    configure_event_loop_policy()
    created, skipped = asyncio.run(_import(args.root, overwrite=args.overwrite))
    print(f"知识文档导入完成：新增 {created} 篇，保留既有 {skipped} 篇")


if __name__ == "__main__":
    main()
