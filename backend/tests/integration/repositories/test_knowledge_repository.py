"""团队知识文档仓储集成测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import Database
from app.knowledge.wiki_seed import seed_wiki_documents
from app.models.knowledge import KnowledgeDocument
from app.repositories.knowledge import KnowledgeRepository


@pytest.mark.asyncio
async def test_upsert_by_source_path_updates_the_existing_document(
    db_session: AsyncSession,
) -> None:
    """若导入重复创建记录，知识检索将返回重复内容。"""

    repository = KnowledgeRepository(db_session)
    await repository.upsert_by_source_path(
        source_path="业务/交易/业务流程/交易业务流程图.md",
        category="TRADE",
        title="交易业务流程图",
        content="下单到履约的流程。",
        source="Borough 团队维护",
        is_complete=True,
    )
    await repository.upsert_by_source_path(
        source_path="业务/交易/业务流程/交易业务流程图.md",
        category="TRADE",
        title="交易业务流程图",
        content="下单到履约的流程（已更新）。",
        source="Borough 团队维护",
        is_complete=True,
    )
    await db_session.flush()

    documents = await repository.list_active()

    assert len(documents) == 1
    assert documents[0].content == "下单到履约的流程（已更新）。"
    assert documents[0].version == 2


@pytest.mark.asyncio
async def test_upsert_preserves_the_incomplete_knowledge_marker(
    db_session: AsyncSession,
) -> None:
    """丢失骨架标记会让后续回答把不完整知识伪装成正式资料。"""

    repository = KnowledgeRepository(db_session)

    await repository.upsert_by_source_path(
        source_path="业务/优惠券/业务名词解释/优惠券名词.md",
        category="COUPON",
        title="优惠券名词",
        content="⚠️ 待团队补充",
        source="Borough 团队维护",
        is_complete=False,
    )
    await db_session.flush()

    documents = await repository.list_active()

    assert documents[0].is_complete is False


@pytest.mark.asyncio
async def test_insert_if_absent_preserves_admin_edited_document(
    db_session: AsyncSession,
) -> None:
    repository = KnowledgeRepository(db_session)
    source_path = "业务/商品/上架规则.md"
    await repository.upsert_by_source_path(
        source_path=source_path,
        category="GOODS",
        title="上架规则",
        content="管理员维护的版本",
        source="Borough 团队维护",
        is_complete=True,
    )

    created = await repository.insert_if_absent_by_source_path(
        source_path=source_path,
        category="GOODS",
        title="上架规则",
        content="镜像种子版本",
        source="Borough 镜像知识种子",
        is_complete=True,
    )
    await db_session.flush()

    documents = await repository.list_active()
    assert created is False
    assert documents[0].content == "管理员维护的版本"
    assert documents[0].version == 1


@pytest.mark.asyncio
async def test_image_seed_is_idempotent_and_preserves_admin_edits(
    integration_database: Database,
) -> None:
    assert await seed_wiki_documents(integration_database) == 21

    async with integration_database.session() as session:
        document = await session.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.category == "GOODS")
            .order_by(KnowledgeDocument.source_path)
        )
        assert document is not None
        document_id = document.id
        document.content = "管理员更新后的上架规则"
        await session.commit()

    assert await seed_wiki_documents(integration_database) == 0
    async with integration_database.session() as session:
        document = await session.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        )
    assert document is not None
    assert document.content == "管理员更新后的上架规则"
