"""镜像内团队知识种子的读取与非覆盖式落库。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.session import Database
from app.repositories.knowledge import KnowledgeRepository

_SEED_FILE = Path(__file__).with_name("wiki_seed.json")


@dataclass(frozen=True)
class WikiSeedEntry:
    source_path: str
    category: str
    title: str
    content: str
    is_complete: bool
    source: str


def load_wiki_seed_entries(path: Path = _SEED_FILE) -> list[WikiSeedEntry]:
    """读取构建期快照；字段不完整即视为镜像构建错误。"""

    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("知识种子格式无效")
    try:
        return [WikiSeedEntry(**item) for item in raw]
    except (TypeError, ValueError) as error:
        raise RuntimeError("知识种子字段无效") from error


async def seed_wiki_documents(database: Database) -> int:
    """以 insert-if-absent 语义补齐镜像中新增的团队知识。"""

    entries = load_wiki_seed_entries()
    created = 0
    async with database.session() as session:
        repository = KnowledgeRepository(session)
        for entry in entries:
            if await repository.insert_if_absent_by_source_path(
                source_path=entry.source_path,
                category=entry.category,
                title=entry.title,
                content=entry.content,
                source=entry.source,
                is_complete=entry.is_complete,
            ):
                created += 1
        await session.commit()
    return created
