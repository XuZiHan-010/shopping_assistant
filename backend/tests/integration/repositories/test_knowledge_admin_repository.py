"""后台仓储：前缀查询、大小写冲突、批量改前缀。"""

from __future__ import annotations

import pytest

from app.repositories.knowledge_admin import KnowledgeAdminRepository

pytestmark = pytest.mark.integration


async def test_list_paths_filters_by_prefix(db_session) -> None:
    repository = KnowledgeAdminRepository(db_session)
    await repository.create(
        virtual_path="业务/交易/业务流程/下单.md", category="TRADE", title="下单", content="a"
    )
    await repository.create(
        virtual_path="业务/退货/业务流程/退货.md", category="REFUND", title="退货", content="b"
    )
    await db_session.flush()

    rows = await repository.list_paths("业务/交易/")

    assert [row.source_path for row in rows] == ["业务/交易/业务流程/下单.md"]


async def test_find_case_insensitive_detects_conflict(db_session) -> None:
    """参考实现 rejectCaseInsensitiveConflict：大小写不同的同名节点视为冲突。"""

    repository = KnowledgeAdminRepository(db_session)
    await repository.create(
        virtual_path="index/Readme.md", category="UNKNOWN", title="Readme", content="a"
    )
    await db_session.flush()

    assert await repository.find_case_insensitive("index", "readme.md") is not None
    assert await repository.find_case_insensitive("index", "other.md") is None


async def test_move_prefix_rewrites_every_descendant(db_session) -> None:
    repository = KnowledgeAdminRepository(db_session)
    for section in ("业务流程", "业务名词解释"):
        await repository.create(
            virtual_path=f"业务/旧域/{section}/a.md",
            category="TRADE",
            title="a",
            content="x",
        )
    await db_session.flush()

    moved = await repository.move_prefix("业务/旧域/", "业务/新域/")
    await db_session.flush()

    assert moved == 2
    assert await repository.count_under("业务/旧域/") == 0
    assert await repository.count_under("业务/新域/") == 2


async def test_update_content_bumps_version(db_session) -> None:
    repository = KnowledgeAdminRepository(db_session)
    document = await repository.create(
        virtual_path="index/a.md", category="UNKNOWN", title="a", content="v1"
    )
    await db_session.flush()

    await repository.update_content(document, "v2")
    await db_session.flush()

    assert document.content == "v2"
    assert document.version == 2


async def test_conditional_update_rejects_a_stale_content_snapshot(db_session) -> None:
    repository = KnowledgeAdminRepository(db_session)
    document = await repository.create(
        virtual_path="index/cas.md", category="UNKNOWN", title="cas", content="v1"
    )
    await db_session.flush()

    updated = await repository.update_content_if_current(document.id, "v1", "v2")
    stale = await repository.update_content_if_current(document.id, "v1", "v3")

    assert updated is not None
    assert updated.content == "v2"
    assert stale is None
